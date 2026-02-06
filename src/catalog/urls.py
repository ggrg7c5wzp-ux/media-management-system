from django.urls import path
from django.views.generic import RedirectView
from .views_reports import first_last_by_physical_bin_pdf
from .views import (
    DashboardView,
    CatalogListView,
    ArtistListView,
    ArtistDetailView,
    MediaItemDetailView,
    TagListView,
    TagDetailView,
    GenreListView,
    GenreDetailView,
    MediaTypeListView,
    MediaTypeDetailView,
    CuratedView,
    EarlyWarningView,
    FirstLastByBinView,
    RebinPreviewPdfView,
)

app_name = "catalog_public"

urlpatterns = [
    # Root -> Catalog (fixes onrender root 500)
    path("", RedirectView.as_view(url="/catalog/", permanent=False), name="root"),

    # Core public views
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("catalog/", CatalogListView.as_view(), name="catalog_list"),

    path("artists/", ArtistListView.as_view(), name="artist_list"),
    path("artists/<int:pk>/", ArtistDetailView.as_view(), name="artist_detail"),

    path("items/<int:pk>/", MediaItemDetailView.as_view(), name="item_detail"),

    # Browse
    path("genres/", GenreListView.as_view(), name="genre_list"),
    path("genres/<int:pk>/", GenreDetailView.as_view(), name="genre_detail"),

    path("media-types/", MediaTypeListView.as_view(), name="media_type_list"),
    path("media-types/<int:pk>/", MediaTypeDetailView.as_view(), name="media_type_detail"),

    path("tags/", TagListView.as_view(), name="tag_list"),
    path("tags/<int:pk>/", TagDetailView.as_view(), name="tag_detail"),

    # Curated
    path("curated/cander/", CuratedView.as_view(), {"key": "cander"}, name="curated_cander"),
    path("curated/darvina/", CuratedView.as_view(), {"key": "darvina"}, name="curated_darvina"),
    path("curated/audiophile/", CuratedView.as_view(), {"key": "audiophile"}, name="curated_audiophile"),

    # Reports (staff-only)
    path("reports/early-warning/", EarlyWarningView.as_view(), name="report_early_warning"),
    path("reports/first-last/", FirstLastByBinView.as_view(), name="report_first_last"),
    path("reports/first-last.pdf", first_last_by_physical_bin_pdf, name="first_last_pdf"),

]