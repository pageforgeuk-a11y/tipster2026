"""HTTP entrypoint for Vercel Cron (spec §9).

Vercel Cron hits this URL on a schedule. It is protected by a shared secret:
Vercel sends `Authorization: Bearer $CRON_SECRET`. No always-on worker required.
"""

import hmac

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .reminders import run_reminders


def _authorised(request) -> bool:
    secret = settings.CRON_SECRET
    if not secret:
        # No secret configured: only allow in DEBUG to avoid an open endpoint.
        return settings.DEBUG
    header = request.headers.get("Authorization", "")
    expected = f"Bearer {secret}"
    return hmac.compare_digest(header, expected)


@csrf_exempt
def send_reminders_endpoint(request):
    if not _authorised(request):
        return JsonResponse({"error": "unauthorised"}, status=401)
    summary = run_reminders()
    return JsonResponse({"status": "ok", **summary})
