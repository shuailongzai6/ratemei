from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import PhotoUploadForm
from .models import Match, Photo, Voter
from .services import VoteError, cast_vote, get_match, skip_match


@transaction.atomic
def get_voter(request):
    """Keep guest choices when the visitor creates an account in the same session."""
    voter_id = request.session.get("voter_id")
    voter = None
    if request.user.is_authenticated:
        voter = Voter.objects.filter(user=request.user).first()
    if voter is None and voter_id:
        voter = Voter.objects.filter(pk=voter_id, user__isnull=True).first()
    if voter is None:
        voter = Voter.objects.create()
    if request.user.is_authenticated and voter.user_id is None:
        voter.user = request.user
        voter.save(update_fields=["user"])
    request.session["voter_id"] = str(voter.pk)
    return voter


def round_context(request, **feedback):
    voter = get_voter(request)
    context = {
        "match": get_match(voter, request.user),
        "photo_count": Photo.objects.count(),
        "voted_count": voter.matches.filter(status=Match.Status.VOTED).count(),
        **feedback,
    }
    if context["match"] is None:
        eligible = Photo.objects.all()
        if request.user.is_authenticated:
            eligible = eligible.exclude(owner=request.user)
        owner_count = eligible.order_by().values("owner_id").distinct().count()
        context["empty_reason"] = "need_photos" if owner_count < 2 else "finished"
    return context


@never_cache
def home(request):
    feedback = request.session.pop("arena_feedback", {})
    return render(request, "arena/home.html", round_context(request, **feedback))


def round_response(request, **feedback):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(request, "arena/_duel.html", round_context(request, **feedback))
    request.session["arena_feedback"] = feedback
    return redirect("arena:home")


@never_cache
@require_POST
def vote(request, match_id):
    voter = get_voter(request)
    try:
        match = cast_vote(match_id, voter, request.POST.get("winner"))
    except VoteError as exc:
        return round_response(request, notice=str(exc))
    counts = Match.objects.filter(
        photo_a_id=match.photo_a_id,
        photo_b_id=match.photo_b_id,
        status=Match.Status.VOTED,
    ).aggregate(total=Count("pk"), support=Count("pk", filter=Q(winner_id=match.winner_id)))
    return round_response(request, result={"name": match.winner.name, **counts})


@never_cache
@require_POST
def skip(request, match_id):
    try:
        skip_match(match_id, get_voter(request))
    except VoteError as exc:
        return round_response(request, notice=str(exc))
    return round_response(request)


def leaderboard(request):
    ranked = list(
        Photo.objects.select_related("owner")
        .filter(Q(wins__gt=0) | Q(losses__gt=0))
        .order_by("-rating", "-wins", "created_at")[:100]
    )
    return render(request, "arena/leaderboard.html", {"podium": ranked[:3], "ranked": ranked[3:]})


@login_required
def photos(request):
    form = PhotoUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        photo = form.save(commit=False)
        photo.owner = request.user
        photo.save()
        return redirect("arena:photos")
    return render(request, "arena/photos.html", {
        "form": form,
        "photos": Photo.objects.filter(owner=request.user).select_related("owner"),
    })


@login_required
@require_POST
def delete_photo(request, pk):
    photo = get_object_or_404(Photo, pk=pk, owner=request.user)
    photo.delete()
    return redirect("arena:photos")


def signup(request):
    if request.user.is_authenticated:
        return redirect("arena:home")
    form = UserCreationForm(request.POST or None)
    next_url = request.POST.get("next", request.GET.get("next", ""))
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        get_voter(request)
        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            next_url = reverse("arena:photos")
        return redirect(next_url)
    return render(request, "registration/signup.html", {"form": form, "next": next_url})
