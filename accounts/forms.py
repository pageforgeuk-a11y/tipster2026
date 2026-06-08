"""Registration + login forms (spec §3, Phase 1).

Accounts are email + password: the email address is used as the Django username,
so there's no separate username to remember. We collect the player's real name
(first/last) and their **team name**, which is what shows on the leaderboards.
Kept behind the standard Django auth layer so social logins (Phase II) slot in.
"""

from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    UserCreationForm,
)
from django.contrib.auth.models import User
from django.template.loader import render_to_string


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(
        required=True, help_text="You'll use this to log in."
    )
    team_name = forms.CharField(
        max_length=120, required=True, label="Team name",
        help_text="Your team — this is what shows on the leaderboards.",
    )

    # Control the on-screen order regardless of base-class declaration order.
    field_order = ["first_name", "last_name", "email", "team_name",
                   "password1", "password2"]

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # Email doubles as the username, so it must be unique on either field.
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(
            username__iexact=email
        ).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.cleaned_data["email"]
        user.username = email  # email is the username
        user.email = email
        if commit:
            user.save()
        return user


class EmailLoginForm(AuthenticationForm):
    """Standard auth, but the username field is the email address."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email address"
        self.fields["username"].widget = forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email"}
        )

    def clean_username(self):
        # Usernames are stored lowercased (= the registration email), so match
        # case-insensitively here too.
        return self.cleaned_data.get("username", "").strip().lower()


class ResendPasswordResetForm(PasswordResetForm):
    """Password reset that sends through our swappable email layer (Resend in
    production, console in dev) rather than Django's email backend directly.

    Token generation and user lookup (by email) are inherited unchanged.
    """

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        from competition.emailing import send_email

        subject = render_to_string(subject_template_name, context)
        subject = "".join(subject.splitlines())  # subject must be single line
        body = render_to_string(email_template_name, context)
        html = (
            render_to_string(html_email_template_name, context)
            if html_email_template_name
            else None
        )
        send_email(to_email, subject, body, html=html)
