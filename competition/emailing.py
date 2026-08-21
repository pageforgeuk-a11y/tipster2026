"""Swappable transactional email (spec §2).

`send_email()` is the single entry point. In production with RESEND_API_KEY set
it uses Resend; otherwise it falls back to Django's email backend (console in
dev, SMTP if EMAIL_PROVIDER=smtp). Keeping it behind one function means the
provider is trivially swappable.
"""

from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _use_resend() -> bool:
    provider = settings.EMAIL_PROVIDER
    if provider == "resend":
        return True
    if provider in ("console", "smtp"):
        return False
    # auto
    return bool(settings.RESEND_API_KEY)


def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    html: str | None = None,
    attachments: list[dict] | None = None,
) -> bool:
    """Send one email. Returns True on success, False on failure (never raises).

    `attachments` is a list of {"filename", "content" (bytes), "content_type"}.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return False

    if _use_resend():
        return _send_via_resend(recipients, subject, body, html, attachments)
    return _send_via_django(recipients, subject, body, html, attachments)


def _send_via_resend(recipients, subject, body, html, attachments=None) -> bool:
    try:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        payload = {
            "from": settings.DEFAULT_FROM_EMAIL,
            "to": recipients,
            "subject": subject,
            "text": body,
            **({"html": html} if html else {}),
        }
        if attachments:
            # Resend expects the raw bytes as a list of ints (see its Attachment type).
            payload["attachments"] = [
                {
                    "filename": a["filename"],
                    "content": list(a["content"]),
                    **({"content_type": a["content_type"]} if a.get("content_type") else {}),
                }
                for a in attachments
            ]
        resend.Emails.send(payload)
        return True
    except Exception as exc:  # noqa: BLE001 - email must never break a request
        logger.error("Resend send failed: %s", exc)
        return False


def _send_via_django(recipients, subject, body, html, attachments=None) -> bool:
    try:
        from django.core.mail import EmailMultiAlternatives

        msg = EmailMultiAlternatives(
            subject, body, settings.DEFAULT_FROM_EMAIL, recipients
        )
        if html:
            msg.attach_alternative(html, "text/html")
        for a in attachments or []:
            msg.attach(
                a["filename"], a["content"], a.get("content_type") or "application/octet-stream"
            )
        msg.send(fail_silently=False)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Email send failed: %s", exc)
        return False
