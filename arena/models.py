import uuid
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _


def photo_upload_path(instance, filename):
    return f"photos/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class Photo(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=photo_upload_path)
    caption = models.CharField(max_length=40, blank=True)
    rating = models.FloatField(default=1000)
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def name(self):
        return self.caption or self.owner.username

    @property
    def comparisons(self):
        return self.wins + self.losses

    def __str__(self):
        return self.name


@receiver(post_delete, sender=Photo)
def delete_photo_file(sender, instance, **kwargs):
    if instance.image:
        transaction.on_commit(lambda: instance.image.delete(save=False))


class Voter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="voter"
    )

    def __str__(self):
        return str(self.id)


class Match(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        VOTED = "voted", _("Voted")
        SKIPPED = "skipped", _("Skipped")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    voter = models.ForeignKey(Voter, on_delete=models.CASCADE, related_name="matches")
    photo_a = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="matches_as_a")
    photo_b = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="matches_as_b")
    swapped = models.BooleanField(default=False)
    winner = models.ForeignKey(
        Photo, on_delete=models.CASCADE, null=True, blank=True, related_name="winning_matches"
    )
    status = models.CharField(max_length=7, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    voted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["voter", "photo_a", "photo_b"], name="unique_voter_pair"),
            models.CheckConstraint(condition=Q(photo_a__lt=F("photo_b")), name="canonical_photo_pair"),
            models.CheckConstraint(
                condition=(
                    Q(status="voted", winner__isnull=False, voted_at__isnull=False)
                    & (Q(winner=F("photo_a")) | Q(winner=F("photo_b")))
                )
                | Q(status__in=["pending", "skipped"], winner__isnull=True, voted_at__isnull=True),
                name="match_result_matches_status",
            ),
        ]

    @property
    def left(self):
        return self.photo_b if self.swapped else self.photo_a

    @property
    def right(self):
        return self.photo_a if self.swapped else self.photo_b

    def __str__(self):
        return f"{self.photo_a_id} vs {self.photo_b_id}: {self.status}"
