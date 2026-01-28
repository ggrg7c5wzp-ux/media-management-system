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


from django.db.models import Q, Count
from django.views.generic import ListView, DetailView

from .models import Artist, MediaItem


class ArtistListView(ListView):
    model = Artist
    template_name = "catalog/artist_list.html"
    context_object_name = "artists"
    paginate_by = 200  # only used when we’re actually showing a list

    def get_queryset(self):
        qs = (
            Artist.objects
            .all()
            .annotate(item_count=Count("media_items", distinct=True))
            .order_by("sort_name", "display_name", "pk")
        )

        q = (self.request.GET.get("q") or "").strip()
        letter = (self.request.GET.get("letter") or "").strip().upper()

        # Search mode (overrides letters)
        if q:
            return qs.filter(Q(display_name__icontains=q) | Q(sort_name__icontains=q))

        # Browse-by-letter mode
        if letter:
            if letter == "#":
                # non A-Z bucket
                return qs.exclude(alpha_bucket__range=("A", "Z"))
            return qs.filter(alpha_bucket=letter)

        # No search and no letter selected:
        # return empty list; template will show the A-Z directory UI
        return qs.none()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        q = (self.request.GET.get("q") or "").strip()
        letter = (self.request.GET.get("letter") or "").strip().upper()

        ctx["q"] = q
        ctx["letter"] = letter

        # Counts for the A-Z directory (only needed when not searching)
        counts_qs = Artist.objects.values("alpha_bucket").annotate(c=Count("id"))
        ctx["letter_counts"] = {row["alpha_bucket"]: row["c"] for row in counts_qs}

        return ctx



class ArtistDetailView(DetailView):
    model = Artist
    template_name = "catalog/artist_detail.html"
    context_object_name = "artist"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        artist = self.object

        # Records for this artist
        items_qs = (
            MediaItem.objects
            .filter(artist=artist)
            .select_related("media_type", "storage_zone")
            .order_by("title", "pressing_year", "pk")
        )

        ctx["items"] = items_qs
        ctx["item_count"] = items_qs.count()

        # Breakdown by Media Type
        ctx["by_media_type"] = (
            items_qs.values("media_type__name")
            .annotate(c=Count("id"))
            .order_by("-c", "media_type__name")
        )

        # Breakdown by Storage Zone
        ctx["by_zone"] = (
            items_qs.values("storage_zone__name", "storage_zone__code")
            .annotate(c=Count("id"))
            .order_by("-c", "storage_zone__name")
        )

        # Optional: year range (helps “profile” feel)
        years = list(items_qs.values_list("pressing_year", flat=True))
        years = [y for y in years if y]
        ctx["year_min"] = min(years) if years else None
        ctx["year_max"] = max(years) if years else None

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
