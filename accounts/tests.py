"""Registration + login: email-as-username, real name, team name."""

import re

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from competition.models import Participant, Season


class RegistrationTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)

    def _post(self, **overrides):
        data = {
            "first_name": "Alice",
            "last_name": "Adams",
            "email": "Alice@Example.com",
            "team_name": "Red Lion Rovers",
            "password1": "swordfish-trombone-9",
            "password2": "swordfish-trombone-9",
        }
        data.update(overrides)
        return self.client.post(reverse("register"), data)

    def test_registration_creates_user_and_participant(self):
        resp = self._post()
        self.assertRedirects(resp, reverse("dashboard"))

        user = User.objects.get(email="alice@example.com")
        # Email (lowercased) is the username.
        self.assertEqual(user.username, "alice@example.com")
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.last_name, "Adams")

        participant = Participant.objects.get(user=user)
        self.assertEqual(participant.display_name, "Red Lion Rovers")  # team name
        self.assertEqual(participant.season, self.season)

    def test_duplicate_email_rejected_case_insensitively(self):
        self._post()
        resp = self._post(email="ALICE@example.com", team_name="Other")
        self.assertEqual(resp.status_code, 200)  # re-rendered with error
        self.assertEqual(User.objects.filter(email__iexact="alice@example.com").count(), 1)

    def test_login_with_email_any_case(self):
        self._post()
        ok = self.client.login(username="alice@example.com", password="swordfish-trombone-9")
        self.assertTrue(ok)
        # And through the login view, with mixed-case email.
        resp = self.client.post(
            reverse("login"),
            {"username": "ALICE@EXAMPLE.COM", "password": "swordfish-trombone-9"},
        )
        self.assertRedirects(resp, reverse("dashboard"))


class PasswordResetTests(TestCase):
    def setUp(self):
        Season.objects.create(name="S", is_active=True)
        self.user = User.objects.create_user(
            username="alice@example.com",
            email="alice@example.com",
            password="old-password-123",
            first_name="Alice",
        )

    def test_reset_email_sent_and_new_password_works(self):
        # Request a reset by email.
        resp = self.client.post(reverse("password_reset"), {"email": "alice@example.com"})
        self.assertRedirects(resp, reverse("password_reset_done"))

        # Email went out (through our layer -> locmem in tests).
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("K.H.S.S.C.", mail.outbox[0].subject)

        # Pull the reset link and follow it to set a new password.
        match = re.search(r"/accounts/reset/[^/\s]+/[^/\s]+/", body)
        self.assertIsNotNone(match, "reset link missing from email")
        url = match.group(0)
        resp = self.client.get(url)  # redirects to the set-password form
        self.assertEqual(resp.status_code, 302)
        confirm_url = resp.url

        resp = self.client.post(
            confirm_url,
            {"new_password1": "fresh-password-456", "new_password2": "fresh-password-456"},
        )
        self.assertRedirects(resp, reverse("password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("fresh-password-456"))

    def test_reset_for_unknown_email_still_succeeds_quietly(self):
        # Don't leak which emails exist: response is the same, no email sent.
        resp = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)
