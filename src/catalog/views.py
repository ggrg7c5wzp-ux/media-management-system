# src/catalog/views.py
from django.views.generic import ListView, DetailView

from .models import Artist, MediaItem


class CatalogListView(ListView):
    model = MediaItem
    template_name = "catalog/catalog_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        return (
            MediaItem.objects
            .select_related("artist", "media_type", "logical_bin", "bucket", "zone_override")
            .order_by("artist__sort_name", "title", "pk")
        )


class ArtistListView(ListView):
    model = Artist
    template_name = "catalog/artist_list.html"
    context_object_name = "artists"
    paginate_by = 100

    def get_queryset(self):
        return Artist.objects.all().order_by("sort_name", "display_name", "pk")


class ArtistDetailView(DetailView):
    model = Artist
    template_name = "catalog/artist_detail.html"
    context_object_name = "artist"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        artist = self.get_object()
        ctx["items"] = (
            MediaItem.objects
            .filter(artist=artist)
            .select_related("media_type", "logical_bin", "bucket", "zone_override")
            .order_by("title", "pk")
        )
        return ctx
