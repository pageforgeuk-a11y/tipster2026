"""Swappable transactional email (spec §2).

`send_email()` is the single entry point. In production with RESEND_API_KEY set
it uses Resend; otherwise it falls back to Django's email backend (console in
dev, SMTP if EMAIL_PROVIDER=smtp). Keeping it behind one function means the
provider is trivially swappable.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _use_resend() -> bool:
    provider = settings.EMAIL_PROVIDER
    if provider == "resend":
        return True
    if provider in ("console", "smtp"):
        return False
    # auto
    return bool(settings.RESEND_API_KEY)


def send_email(to: str | list[str], subject: str, body: str, html: str | None = None) -> bool:
    """Send one email. Returns True on success, False on failure (never raises)."""
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return False

    if _use_resend():
        return _send_via_resend(recipients, subject, body, html)
    return _send_via_django(recipients, subject, body, html)


def _send_via_resend(recipients, subject, body, html) -> bool:
    try:
        import resend

        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send(
            {
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": recipients,
                "subject": subject,
                "text": body,
                **({"html": html} if html else {}),
            }
        )
        return True
    except Exception as exc:  # noqa: BLE001 - email must never break a request
        logger.error("Resend send failed: %s", exc)
        return False


def _send_via_django(recipients, subject, body, html) -> bool:
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            recipients,
            html_message=html,
            fail_silently=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Email send failed: %s", exc)
        return False
