from django.urls import path
from django.views.generic import RedirectView
from .views import (
    DashboardView,
    CatalogListView,
    ArtistListView,
    ArtistDetailView,
    MediaItemDetailView,
)

app_name = "catalog_public"

urlpatterns = [    # NEW: dashboard is the app root
    path("", DashboardView.as_view(), name="dashboard"),
    path("", RedirectView.as_view(pattern_name="catalog_public:catalog_list", permanent=False)),
    path("catalog/", CatalogListView.as_view(), name="catalog_list"),
    path("artists/", ArtistListView.as_view(), name="artist_list"),
    path("artists/<int:pk>/", ArtistDetailView.as_view(), name="artist_detail"),
    path("items/<int:pk>/", MediaItemDetailView.as_view(), name="item_detail"),
]
