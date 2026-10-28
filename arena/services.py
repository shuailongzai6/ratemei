import random

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Match, Photo, Voter


class VoteError(Exception):
    pass


@transaction.atomic
def get_match(voter, user=None):
    """Reuse a pending pair, or sample an unseen pair without building every pair in memory."""
    Voter.objects.select_for_update().get(pk=voter.pk)
    owner_id = user.pk if user is not None and user.is_authenticated else voter.user_id
    pending = Match.objects.filter(voter=voter, status=Match.Status.PENDING)
    if owner_id is not None:
        pending.filter(Q(photo_a__owner_id=owner_id) | Q(photo_b__owner_id=owner_id)).update(
            status=Match.Status.SKIPPED
        )
    match = pending.select_related("photo_a__owner", "photo_b__owner").first()
    if match:
        return match

    photos = Photo.objects.all()
    if owner_id is not None:
        photos = photos.exclude(owner_id=owner_id)

    # Check both orientations so sampling does not favor newer photo IDs.
    seen = Match.objects.filter(voter=voter).filter(
        Q(photo_a_id=OuterRef(OuterRef("pk")), photo_b_id=OuterRef("pk"))
        | Q(photo_b_id=OuterRef(OuterRef("pk")), photo_a_id=OuterRef("pk"))
    )
    opponents = (
        photos.exclude(owner_id=OuterRef("owner_id"))
        .filter(~Exists(seen))
    )
    first = photos.filter(Exists(opponents)).select_related("owner").order_by("?").first()
    if first is None:
        return None

    seen_opponents = Match.objects.filter(voter=voter).filter(
        Q(photo_a=first, photo_b_id=OuterRef("pk"))
        | Q(photo_b=first, photo_a_id=OuterRef("pk"))
    )
    second = (
        photos.exclude(owner_id=first.owner_id)
        .filter(~Exists(seen_opponents))
        .select_related("owner")
        .order_by("?")
        .first()
    )
    photo_a, photo_b = sorted([first, second], key=lambda photo: photo.pk)
    return Match.objects.create(
        voter=voter, photo_a=photo_a, photo_b=photo_b, swapped=random.choice([True, False])
    )


def _pending_match(match_id, voter):
    Voter.objects.select_for_update().get(pk=voter.pk)
    try:
        match = Match.objects.select_for_update().get(pk=match_id, voter=voter)
    except Match.DoesNotExist:
        raise VoteError(_("This matchup is no longer available.")) from None
    if match.status != Match.Status.PENDING:
        raise VoteError(_("This matchup has already been answered."))
    return match


@transaction.atomic
def cast_vote(match_id, voter, winner_id):
    match = _pending_match(match_id, voter)
    try:
        winner_id = int(winner_id)
    except (TypeError, ValueError):
        raise VoteError(_("Choose one of the two photos.")) from None
    if winner_id not in (match.photo_a_id, match.photo_b_id):
        raise VoteError(_("Choose one of the two photos."))

    # Lock in ID order, so different voters cannot overwrite each other's Elo updates.
    photos = list(
        Photo.objects.select_for_update()
        .filter(pk__in=[match.photo_a_id, match.photo_b_id])
        .order_by("pk")
    )
    if voter.user_id is not None and any(photo.owner_id == voter.user_id for photo in photos):
        raise VoteError(_("You cannot vote on your own photo."))
    winner, loser = sorted(photos, key=lambda photo: photo.pk != winner_id)
    expected = 1 / (1 + 10 ** ((loser.rating - winner.rating) / 400))
    change = 32 * (1 - expected)
    winner.rating += change
    winner.wins += 1
    loser.rating -= change
    loser.losses += 1
    winner.save(update_fields=["rating", "wins"])
    loser.save(update_fields=["rating", "losses"])

    match.winner = winner
    match.status = Match.Status.VOTED
    match.voted_at = timezone.now()
    match.save(update_fields=["winner", "status", "voted_at"])
    return match


@transaction.atomic
def skip_match(match_id, voter):
    match = _pending_match(match_id, voter)
    match.status = Match.Status.SKIPPED
    match.save(update_fields=["status"])
    return match
