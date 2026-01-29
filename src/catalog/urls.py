from django.urls import path
from django.views.generic import RedirectView
from .views import (
    DashboardView,
    CatalogListView,
    ArtistListView,
    ArtistDetailView,
    MediaItemDetailView,
    TagListView,
    TagDetailView,
)

app_name = "catalog_public"

urlpatterns = [
    # Root -> Catalog (fixes onrender root 500)
    path("", RedirectView.as_view(url="/catalog/", permanent=False), name="root"),

    # Public views
    path("catalog/", CatalogListView.as_view(), name="catalog_list"),
    path("artists/", ArtistListView.as_view(), name="artist_list"),
    path("artists/<int:pk>/", ArtistDetailView.as_view(), name="artist_detail"),
    path("items/<int:pk>/", MediaItemDetailView.as_view(), name="item_detail"),

    # Optional: keep a dashboard if you want it
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("tags/", TagListView.as_view(), name="tag_list"),
    path("tags/<int:pk>/", TagDetailView.as_view(), name="tag_detail"),
]
