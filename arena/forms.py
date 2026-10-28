from io import BytesIO

from django import forms
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps

from .models import Photo


class PhotoUploadForm(forms.ModelForm):
    consent = forms.BooleanField(
        label=_("This is my photo, and I agree to display it in public voting."),
    )

    class Meta:
        model = Photo
        fields = ["image", "caption", "consent"]
        labels = {"image": _("Your photo"), "caption": _("Display name")}
        help_texts = {
            "image": _("JPEG, PNG or WebP, up to 10 MB."),
            "caption": _("Optional. Your username is used if you leave this blank."),
        }
        widgets = {
            "image": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
            "caption": forms.TextInput(attrs={"autocomplete": "off", "maxlength": 40}),
        }

    def clean_image(self):
        upload = self.cleaned_data["image"]
        if upload.size > settings.MAX_UPLOAD_BYTES:
            raise forms.ValidationError(_("Please choose a photo smaller than 10 MB."))
        try:
            with Image.open(upload) as original:
                if original.format not in {"JPEG", "PNG", "WEBP"}:
                    raise forms.ValidationError(_("Please choose a JPEG, PNG or WebP photo."))
                if original.width * original.height > 25_000_000:
                    raise forms.ValidationError(_("Please choose a photo under 25 megapixels."))
                image = ImageOps.exif_transpose(original)
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                # Flatten transparency and discard metadata, including location information.
                rgba = image.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
                output = BytesIO()
                clean.save(output, format="JPEG", quality=88, optimize=True)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise forms.ValidationError(
                _("This photo could not be read. Please choose a different image.")
            ) from exc
        return ContentFile(output.getvalue(), name="photo.jpg")
