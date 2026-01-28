# src/catalog/views.py
from django.db.models import Q, Count
from django.views.generic import ListView, DetailView, TemplateView

from .models import Artist, MediaItem, StorageZone


class CatalogListView(ListView):
    model = MediaItem
    template_name = "catalog/catalog_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            MediaItem.objects
            .select_related("artist", "media_type", "logical_bin", "bucket", "zone_override")
            .order_by("artist__sort_name", "title", "pk")
        )

        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(artist__display_name__icontains=q)
                | Q(artist__sort_name__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx


class ArtistListView(ListView):
    model = Artist
    template_name = "catalog/artist_list.html"
    context_object_name = "artists"
    paginate_by = 100

    def get_queryset(self):
        qs = Artist.objects.all().order_by("sort_name", "display_name", "pk")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(display_name__icontains=q) | Q(sort_name__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        return ctx


class ArtistDetailView(DetailView):
    model = Artist
    template_name = "catalog/artist_detail.html"
    context_object_name = "artist"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        artist = self.get_object()

        q = (self.request.GET.get("q") or "").strip()
        items = (
            MediaItem.objects
            .filter(artist=artist)
            .select_related("media_type", "logical_bin", "bucket", "zone_override")
            .order_by("title", "pk")
        )
        if q:
            items = items.filter(Q(title__icontains=q))

        ctx["items"] = items
        ctx["q"] = q
        return ctx


class MediaItemDetailView(DetailView):
    model = MediaItem
    template_name = "catalog/item_detail.html"
    context_object_name = "item"

    def get_queryset(self):
        return (
            MediaItem.objects
            .select_related("artist", "media_type", "logical_bin", "bucket", "zone_override")
        )
class DashboardView(TemplateView):
    template_name = "catalog/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["counts"] = {
            "artists": Artist.objects.count(),
            "items": MediaItem.objects.count(),
            "zones": StorageZone.objects.count(),
        }

        ctx["zones"] = (
            StorageZone.objects
            .annotate(item_count=Count("media_items", distinct=True))
            .order_by("code")
        )

        return ctx
