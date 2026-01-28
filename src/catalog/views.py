# src/catalog/views.py

from collections import Counter

from django.db.models import Q, Count
from django.views.generic import ListView, DetailView, TemplateView

from .models import Artist, MediaItem, StorageZone, MediaType


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

class DashboardView(TemplateView):
    template_name = "catalog/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["counts"] = {
            "artists": Artist.objects.count(),
            "items": MediaItem.objects.count(),
            "zones": StorageZone.objects.count(),
        }

        zones = list(StorageZone.objects.all().order_by("code"))

        # Count items by effective zone (property):
        # effective_zone = zone_override OR media_type.default_zone
        items = (
            MediaItem.objects
            .select_related("media_type", "media_type__default_zone", "zone_override")
            .only("id", "media_type_id", "zone_override_id")
        )

        # Avoid .id complaints: key the counter by zone.code (string)
        counter = Counter()
        for it in items:
            z = it.effective_zone
            if z:
                counter[z.code] += 1

        ctx["zones"] = [
            {
                "code": z.code,
                "name": z.name,
                "item_count": counter.get(z.code, 0),
            }
            for z in zones
        ]

        return ctx


# -----------------------------------------------------------------------------
# Catalog list (Records table)
# -----------------------------------------------------------------------------

class CatalogListView(ListView):
    model = MediaItem
    template_name = "catalog/catalog_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            MediaItem.objects
            .select_related(
                "artist",
                "media_type",
                "media_type__default_zone",
                "zone_override",
                "logical_bin",
                "bucket",
            )
            .order_by("artist__sort_name", "title", "pk")
        )

        q = (self.request.GET.get("q") or "").strip()
        media = (self.request.GET.get("media") or "").strip()
        zone = (self.request.GET.get("zone") or "").strip()

        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(artist__display_name__icontains=q)
                | Q(artist__sort_name__icontains=q)
            )

        if media:
            qs = qs.filter(media_type__id=media)

        if zone:
            # effective zone = zone_override OR (zone_override is null and media_type.default_zone = zone)
            qs = qs.filter(
                Q(zone_override__id=zone)
                | Q(zone_override__isnull=True, media_type__default_zone__id=zone)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = (self.request.GET.get("q") or "").strip()
        ctx["media"] = (self.request.GET.get("media") or "").strip()
        ctx["zone"] = (self.request.GET.get("zone") or "").strip()

        ctx["media_types"] = MediaType.objects.all().order_by("name")
        ctx["zones"] = StorageZone.objects.all().order_by("code")

        return ctx


# -----------------------------------------------------------------------------
# Artist directory
# -----------------------------------------------------------------------------

class ArtistListView(ListView):
    model = Artist
    template_name = "catalog/artist_list.html"
    context_object_name = "artists"
    paginate_by = 200

    def get_queryset(self):
        qs = (
            Artist.objects
            .annotate(item_count=Count("media_items", distinct=True))
            .order_by("sort_name", "display_name", "pk")
        )

        q = (self.request.GET.get("q") or "").strip()
        letter = (self.request.GET.get("letter") or "").strip().upper()

        if q:
            return qs.filter(
                Q(display_name__icontains=q)
                | Q(sort_name__icontains=q)
            )

        if letter:
            if letter == "#":
                return qs.filter(alpha_bucket="#") | qs.exclude(alpha_bucket__range=("A", "Z"))
            return qs.filter(alpha_bucket=letter)

        return qs.none()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        q = (self.request.GET.get("q") or "").strip()
        letter = (self.request.GET.get("letter") or "").strip().upper()

        ctx["q"] = q
        ctx["letter"] = letter

        raw = Artist.objects.values("alpha_bucket").annotate(c=Count("id"))
        counts = {r["alpha_bucket"]: r["c"] for r in raw}

        ctx["letters"] = [{"ch": ch, "count": counts.get(ch, 0)} for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        ctx["letters"].append({"ch": "#", "count": counts.get("#", 0)})

        return ctx


# -----------------------------------------------------------------------------
# Artist profile
# -----------------------------------------------------------------------------

class ArtistDetailView(DetailView):
    model = Artist
    template_name = "catalog/artist_detail.html"
    context_object_name = "artist"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        artist = self.get_object()

        q = (self.request.GET.get("q") or "").strip()

        items_qs = (
            MediaItem.objects
            .filter(artist=artist)
            .select_related(
                "media_type",
                "media_type__default_zone",
                "zone_override",
                "logical_bin",
                "bucket",
            )
            .order_by("title", "pressing_year", "pk")
        )

        if q:
            items_qs = items_qs.filter(Q(title__icontains=q))

        ctx["q"] = q
        ctx["items"] = items_qs
        ctx["item_count"] = items_qs.count()

        ctx["by_media_type"] = (
            items_qs.values("media_type__name")
            .annotate(c=Count("id"))
            .order_by("-c", "media_type__name")
        )

        zone_counter = Counter()
        for it in items_qs:
            z = it.effective_zone
            if z:
                zone_counter[(z.code, z.name)] += 1

        ctx["by_zone"] = [
            {"code": code, "name": name, "c": count}
            for (code, name), count in zone_counter.most_common()
        ]

        years = [y for y in items_qs.values_list("pressing_year", flat=True) if y]
        ctx["year_min"] = min(years) if years else None
        ctx["year_max"] = max(years) if years else None

        return ctx


# -----------------------------------------------------------------------------
# Media item detail
# -----------------------------------------------------------------------------

class MediaItemDetailView(DetailView):
    model = MediaItem
    template_name = "catalog/item_detail.html"
    context_object_name = "item"

    def get_queryset(self):
        return (
            MediaItem.objects
            .select_related(
                "artist",
                "media_type",
                "media_type__default_zone",
                "zone_override",
                "logical_bin",
                "bucket",
            )
        )
