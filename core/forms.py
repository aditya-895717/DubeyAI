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


class AIProviderForm(StyledFormMixin, forms.ModelForm):
    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": "Leave blank to keep the current key"},
        ),
        help_text="Leave blank when editing to keep the existing key unchanged.",
    )

    class Meta:
        model = AIProvider
        fields = ["name", "api_key", "endpoint_url", "model_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
        # A new provider must be created with a key; editing may leave it blank.
        self.fields["api_key"].required = not self.instance.pk

    def clean_api_key(self):
        value = self.cleaned_data.get("api_key", "")
        if not value and self.instance.pk:
            return self.instance.api_key
        return value
