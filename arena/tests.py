from io import BytesIO
from itertools import combinations
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from PIL import Image, PngImagePlugin

from .models import Match, Photo, Voter
from .services import VoteError, cast_vote, get_match, skip_match


class ArenaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.alice = users.create_user(username="alice")
        cls.bob = users.create_user(username="bob")
        cls.viewer = users.create_user(username="viewer")

    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)

    @staticmethod
    def image_upload():
        image = Image.new("RGBA", (120, 80), (190, 120, 80, 180))
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 degrees when displaying the uploaded image.
        exif[315] = "Private camera owner"
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Location", "Private location")
        content = BytesIO()
        image.save(content, format="PNG", exif=exif, pnginfo=metadata)
        return SimpleUploadedFile("selfie.png", content.getvalue(), content_type="image/png")

    def photo(self, owner):
        return Photo.objects.create(owner=owner, image=self.image_upload())

    def pair(self):
        first, second = self.photo(self.alice), self.photo(self.bob)
        voter = Voter.objects.create()
        return first, second, voter, get_match(voter)

    def test_guest_home_handles_empty_and_single_owner_photo_pools(self):
        self.client.cookies["django_language"] = "en"
        for photo_count in range(3):
            with self.subTest(photo_count=photo_count):
                response = self.client.get(reverse("arena:home"))
                self.assertContains(response, "The first match starts with you.")
                self.assertIsNone(response.context["match"])
                self.assertEqual(response.context["empty_reason"], "need_photos")
            if photo_count < 2:
                self.photo(self.alice)
        self.assertFalse(Match.objects.exists())

    def test_upload_requires_login_and_normalizes_image_without_metadata(self):
        url = reverse("arena:photos")
        response = self.client.post(url, {"image": self.image_upload(), "consent": "on"})
        self.assertRedirects(response, f"{reverse('login')}?next={url}", fetch_redirect_response=False)
        self.assertFalse(Photo.objects.exists())

        self.client.force_login(self.alice)
        response = self.client.post(url, {
            "image": self.image_upload(), "caption": "Alice", "consent": "on",
        })
        self.assertRedirects(response, url, fetch_redirect_response=False)
        photo = Photo.objects.get()
        self.assertEqual((photo.owner_id, photo.caption), (self.alice.pk, "Alice"))
        with photo.image.open("rb") as saved, Image.open(saved) as image:
            self.assertEqual((image.format, image.mode, image.size), ("JPEG", "RGB", (80, 120)))
            self.assertFalse(image.getexif())
            self.assertNotIn("Location", image.info)

    def test_upload_rejects_invalid_or_oversized_images_and_missing_consent(self):
        self.client.force_login(self.alice)
        jpeg = BytesIO()
        Image.new("RGB", (120, 80), "red").save(jpeg, format="JPEG")
        cases = [
            (SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg"), 10_000, "on", "image"),
            (SimpleUploadedFile("truncated.jpg", jpeg.getvalue()[:-30], content_type="image/jpeg"), 10_000, "on", "image"),
            (self.image_upload(), 32, "on", "image"),
            (self.image_upload(), 10_000, "", "consent"),
        ]
        for upload, limit, consent, field in cases:
            with self.subTest(field=field, limit=limit), override_settings(MAX_UPLOAD_BYTES=limit):
                response = self.client.post(reverse("arena:photos"), {
                    "image": upload, "consent": consent,
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertFalse(Photo.objects.exists())

    def test_only_owner_can_delete_photo_and_its_stored_file(self):
        photo = self.photo(self.alice)
        storage, name = photo.image.storage, photo.image.name
        url = reverse("arena:delete_photo", args=[photo.pk])
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())
        self.assertTrue(storage.exists(name))

        self.client.force_login(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        self.assertRedirects(response, reverse("arena:photos"), fetch_redirect_response=False)
        self.assertFalse(Photo.objects.filter(pk=photo.pk).exists())
        self.assertFalse(storage.exists(name))

    def test_matching_excludes_own_photos_and_same_owner_pairs(self):
        self.photo(self.viewer)
        alice_photos = [self.photo(self.alice), self.photo(self.alice)]
        bob_photo = self.photo(self.bob)
        voter = Voter.objects.create(user=self.viewer)
        seen = set()
        for _ in range(2):
            match = get_match(voter, self.viewer)
            self.assertIsNotNone(match)
            self.assertNotEqual(match.photo_a.owner_id, match.photo_b.owner_id)
            self.assertNotIn(self.viewer.pk, [match.photo_a.owner_id, match.photo_b.owner_id])
            seen.add(frozenset([match.photo_a_id, match.photo_b_id]))
            skip_match(match.pk, voter)
        self.assertEqual(seen, {frozenset([photo.pk, bob_photo.pk]) for photo in alice_photos})
        self.assertIsNone(get_match(voter, self.viewer))

    def test_vote_updates_ratings_once_and_rejects_invalid_winner_or_replay(self):
        winner, loser, voter, match = self.pair()
        outsider = self.photo(self.viewer)
        for invalid in [None, "not-a-photo", outsider.pk]:
            with self.subTest(winner=invalid), self.assertRaises(VoteError):
                cast_vote(match.pk, voter, invalid)
        voted = cast_vote(match.pk, voter, winner.pk)
        self.assertEqual((voted.status, voted.winner_id), (Match.Status.VOTED, winner.pk))
        self.assertIsNotNone(voted.voted_at)
        with self.assertRaises(VoteError):
            cast_vote(match.pk, voter, loser.pk)
        winner.refresh_from_db()
        loser.refresh_from_db()
        self.assertEqual((winner.rating, winner.wins, winner.losses), (1016, 1, 0))
        self.assertEqual((loser.rating, loser.wins, loser.losses), (984, 0, 1))

    def test_another_voter_cannot_vote_or_skip_someone_elses_match(self):
        first, second, _, match = self.pair()
        stranger = Voter.objects.create()
        with self.assertRaises(VoteError):
            cast_vote(match.pk, stranger, first.pk)
        with self.assertRaises(VoteError):
            skip_match(match.pk, stranger)
        match.refresh_from_db()
        self.assertEqual(match.status, Match.Status.PENDING)
        self.assertEqual(list(Photo.objects.order_by("pk").values_list("rating", flat=True)), [1000, 1000])

    def test_skipping_records_no_vote_and_does_not_change_scores(self):
        first, second, voter, match = self.pair()
        skipped = skip_match(match.pk, voter)
        self.assertEqual(skipped.status, Match.Status.SKIPPED)
        self.assertIsNone(skipped.winner_id)
        self.assertIsNone(skipped.voted_at)
        with self.assertRaises(VoteError):
            cast_vote(match.pk, voter, first.pk)
        for photo in [first, second]:
            photo.refresh_from_db()
            self.assertEqual((photo.rating, photo.comparisons), (1000, 0))
        self.assertIsNone(get_match(voter))

    def test_pending_pair_is_reused_and_all_unseen_pairs_eventually_exhaust(self):
        photos = [self.photo(owner) for owner in [self.alice, self.bob, self.viewer]]
        voter = Voter.objects.create()
        seen = set()
        for index in range(3):
            match = get_match(voter)
            self.assertEqual(get_match(voter).pk, match.pk)
            seen.add((match.photo_a_id, match.photo_b_id))
            if index % 2:
                cast_vote(match.pk, voter, match.photo_a_id)
            else:
                skip_match(match.pk, voter)
        self.assertEqual(seen, set(combinations([photo.pk for photo in photos], 2)))
        self.assertIsNone(get_match(voter))

    def test_language_switch_localizes_both_page_and_vote_error(self):
        self.photo(self.alice)
        self.photo(self.bob)
        for language in ["en", "zh-hans", "en"]:
            with self.subTest(language=language):
                response = self.client.post(reverse("set_language"), {
                    "language": language, "next": reverse("arena:home"),
                }, follow=True)
                self.assertEqual(response["Content-Language"], language)
                with translation.override(language):
                    heading = translation.gettext("Two photos.")
                    error = translation.gettext("Choose one of the two photos.")
                if language == "zh-hans":
                    self.assertNotEqual(heading, "Two photos.")
                    self.assertNotEqual(error, "Choose one of the two photos.")
                self.assertContains(response, heading)
                match = response.context["match"]
                response = self.client.post(reverse("arena:vote", args=[match.pk]), {
                    "winner": "invalid",
                }, follow=True)
                self.assertContains(response, error)
                match.refresh_from_db()
                self.assertEqual(match.status, Match.Status.PENDING)

    def test_guest_vote_requires_csrf_token_from_rendered_form(self):
        self.photo(self.alice)
        self.photo(self.bob)
        client = Client(enforce_csrf_checks=True)
        response = client.get(reverse("arena:home"))
        match = response.context["match"]
        url = reverse("arena:vote", args=[match.pk])
        self.assertEqual(client.post(url, {"winner": match.photo_a_id}).status_code, 403)
        match.refresh_from_db()
        self.assertEqual(match.status, Match.Status.PENDING)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        response = client.post(url, {
            "winner": match.photo_a_id, "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        })
        self.assertRedirects(response, reverse("arena:home"), fetch_redirect_response=False)
        match.refresh_from_db()
        self.assertEqual(match.status, Match.Status.VOTED)

    def test_signup_preserves_guest_votes(self):
        self.photo(self.alice)
        self.photo(self.bob)
        match = self.client.get(reverse("arena:home")).context["match"]
        self.client.post(reverse("arena:vote", args=[match.pk]), {"winner": match.photo_a_id})
        response = self.client.post(reverse("signup"), {
            "username": "newplayer",
            "password1": "A-sensible-demo-password-482!",
            "password2": "A-sensible-demo-password-482!",
        })
        self.assertRedirects(response, reverse("arena:photos"), fetch_redirect_response=False)
        voter = Voter.objects.get(pk=match.voter_id)
        self.assertEqual(voter.user.username, "newplayer")
        self.assertEqual(self.client.session["voter_id"], str(voter.pk))
        self.assertEqual(voter.matches.filter(status=Match.Status.VOTED).count(), 1)
