"""Authentication backends.

Accounts are email-based (the email doubles as the username at registration),
but some accounts have a `username` that differs from their email — notably any
superuser created with `createsuperuser`, or accounts made in the admin/imported.
Django's default `ModelBackend` authenticates on an exact `username` match, so
after a password reset (which finds the user by *email*) those accounts couldn't
log in: the login form authenticates with `username=<email>`, which didn't match.

`EmailBackend` looks the user up by email instead, closing that gap. It's listed
ahead of `ModelBackend` in AUTHENTICATION_BACKENDS, which stays as a fallback so
username-based admin login keeps working.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Authenticate by email address (case-insensitive), ignoring username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        # The login form passes the email as `username`; also accept the model's
        # configured username kwarg for completeness.
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        email = username.strip().lower()
        try:
            user = UserModel.objects.get(email__iexact=email)
        except UserModel.DoesNotExist:
            # Run the hasher once anyway to blunt timing-based user enumeration
            # (mirrors ModelBackend's own behaviour).
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            # Ambiguous email — fall back to an exact username match if one exists.
            user = UserModel.objects.filter(username=email).first()
            if user is None:
                return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
