# src/catalog/urls.py
from django.urls import path

from .views import CatalogListView, ArtistListView, ArtistDetailView

app_name = "catalog_public"

urlpatterns = [
    path("catalog/", CatalogListView.as_view(), name="catalog_list"),
    path("artists/", ArtistListView.as_view(), name="artist_list"),
    path("artists/<int:pk>/", ArtistDetailView.as_view(), name="artist_detail"),
]
