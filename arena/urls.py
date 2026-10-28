from django.urls import path

from . import views

app_name = "arena"
urlpatterns = [
    path("", views.home, name="home"),
    path("vote/<uuid:match_id>/", views.vote, name="vote"),
    path("skip/<uuid:match_id>/", views.skip, name="skip"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    path("photos/", views.photos, name="photos"),
    path("photos/<int:pk>/delete/", views.delete_photo, name="delete_photo"),
]
