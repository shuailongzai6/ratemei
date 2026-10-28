from django.contrib import admin

from .models import Match, Photo, Voter


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ["id", "owner", "caption", "rating", "wins", "losses", "created_at"]
    search_fields = ["owner__username", "caption"]
    readonly_fields = ["rating", "wins", "losses", "created_at"]


@admin.register(Voter)
class VoterAdmin(admin.ModelAdmin):
    list_display = ["id", "user"]
    search_fields = ["user__username"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ["id", "voter", "photo_a", "photo_b", "status", "winner", "created_at"]
    list_filter = ["status"]
    readonly_fields = [field.name for field in Match._meta.fields]

    def has_add_permission(self, request):
        return False
