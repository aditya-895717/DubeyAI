from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User


class StyledFormMixin:
    """Apply Bootstrap form-control class to all fields."""

    def apply_styles(self):
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
            field.widget.attrs.setdefault("autocomplete", "off")


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter your username",
                "autocomplete": "username",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter your password",
                "autocomplete": "current-password",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class RegisterForm(StyledFormMixin, UserCreationForm):
    email = forms.EmailField(
        max_length=254,
        required=True,
        widget=forms.EmailInput(
            attrs={"placeholder": "you@company.com", "autocomplete": "email"}
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "password1", "password2")
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "placeholder": "Choose a username",
                    "autocomplete": "username",
                }
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
        self.fields["password1"].widget.attrs.update(
            {
                "placeholder": "Create a strong password",
                "autocomplete": "new-password",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "placeholder": "Confirm your password",
                "autocomplete": "new-password",
            }
        )

    def clean_username(self):
        """Ensure username is not already taken (case-insensitive)."""
        username = self.cleaned_data.get("username", "").strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                "That username is already taken. Please choose another."
            )
        return username

    def clean_email(self):
        """Ensure no duplicate e-mail addresses."""
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )
        return email

    # NOTE: Do NOT override clean_password2() and call super().clean_password2()
    # here. UserCreationForm.clean_password2() is already called automatically
    # by Django's form validation machinery via the MRO. Calling it explicitly
    # via super() from a mixin chain causes an AttributeError because
    # StyledFormMixin (which sits between RegisterForm and UserCreationForm in
    # the MRO) does not define clean_password2, making Python's super() lookup
    # fail at runtime. Password matching and strength validation are fully
    # handled by UserCreationForm + AUTH_PASSWORD_VALIDATORS in settings.py.
