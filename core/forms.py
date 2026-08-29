from django import forms

from core.models import AIProvider, ContentBlock, SiteSettings


class StyledFormMixin:
    """Apply a consistent CSS class to all fields for the control panel theme."""

    def apply_styles(self):
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (existing + " cp-input").strip()


class SiteSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [
            "site_name",
            "logo",
            "primary_color",
            "secondary_color",
            "accent_color",
            "font_family",
        ]
        widgets = {
            "primary_color": forms.TextInput(attrs={"type": "color"}),
            "secondary_color": forms.TextInput(attrs={"type": "color"}),
            "accent_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class ContentBlockForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ContentBlock
        fields = ["key", "value"]
        widgets = {"value": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class WriteOnlyApiKeyMixin:
    """Never render a stored API key back to the browser.

    The key is decrypted transparently by EncryptedTextField, so a plain
    ModelForm would echo the real secret into the HTML. PasswordInput with
    render_value=False keeps the input empty, and a blank submission is treated
    as "keep the existing key" rather than as "clear the key".
    """

    def init_api_key_field(self):
        # A new provider must be created with a key; editing may leave it blank.
        self.fields["api_key"].required = not self.instance.pk

    def clean_api_key(self):
        value = self.cleaned_data.get("api_key", "")
        if not value and self.instance.pk:
            return self.instance.api_key
        return value


def api_key_form_field(required=False):
    return forms.CharField(
        required=required,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": "Leave blank to keep the current key"},
        ),
        help_text="Encrypted at rest. Leave blank when editing to keep the existing key.",
    )


class AIProviderForm(WriteOnlyApiKeyMixin, StyledFormMixin, forms.ModelForm):
    api_key = api_key_form_field()

    class Meta:
        model = AIProvider
        fields = ["name", "provider_type", "api_key", "endpoint_url", "model_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
        self.init_api_key_field()


class AIProviderAdminForm(WriteOnlyApiKeyMixin, forms.ModelForm):
    """Django admin variant — same write-only key handling, no control-panel CSS."""

    api_key = api_key_form_field()

    class Meta:
        model = AIProvider
        fields = ["name", "provider_type", "api_key", "endpoint_url", "model_name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_api_key_field()
