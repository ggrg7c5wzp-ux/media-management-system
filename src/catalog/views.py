# src/catalog/views.py

from __future__ import annotations

from collections import Counter
from typing import cast
from urllib.parse import urlencode
from django.utils.text import slugify

from django.db.models import Q, Count, Prefetch
from django.views.generic import ListView, DetailView, TemplateView

from .models import Artist, MediaItem, StorageZone, MediaType, Tag


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _base_qs(params: dict) -> str:
    """Build a safe querystring without empty values (no leading '?')."""
    clean = {k: v for k, v in params.items() if v not in ("", None)}
    return urlencode(clean)


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

class DashboardView(TemplateView):
    template_name = "catalog/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.utils.text import slugify

        curated_names = ["Mike's Picks", "New Additions", "Frequently Played"]
        curated = []
        for name in curated_names:
            slug = slugify(name)
            t = Tag.objects.filter(scope=Tag.Scope.MEDIA_ITEM, slug=slug).first()
            curated.append({"name": name, "tag": t})

        ctx["curated_tags"] = curated

        ctx["counts"] = {
            "artists": Artist.objects.count(),
            "items": MediaItem.objects.count(),
            "zones": StorageZone.objects.count(),
        }

        zones = list(StorageZone.objects.all().order_by("code"))

        items = (
            MediaItem.objects
            .select_related("media_type", "media_type__default_zone", "zone_override")
            .only("id", "media_type_id", "zone_override_id")
        )

        counter = Counter()
        for it in items:
            z = it.effective_zone
            if z:
                counter[z.code] += 1

        ctx["zones"] = [
            {"code": z.code, "name": z.name, "item_count": counter.get(z.code, 0)}
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
            qs = qs.filter(
                Q(zone_override__id=zone)
                | Q(zone_override__isnull=True, media_type__default_zone_id=zone)
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["q"] = (self.request.GET.get("q") or "").strip()
        ctx["media"] = (self.request.GET.get("media") or "").strip()
        ctx["zone"] = (self.request.GET.get("zone") or "").strip()

        ctx["media_types"] = MediaType.objects.all().order_by("name")
        ctx["zones"] = StorageZone.objects.all().order_by("code")

        ctx["base_qs"] = _base_qs({"q": ctx["q"], "media": ctx["media"], "zone": ctx["zone"]})
        ctx["list_url_name"] = "catalog_public:catalog_list"
        ctx["active_tag"] = None
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
            return qs.filter(Q(display_name__icontains=q) | Q(sort_name__icontains=q))

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

    def get_queryset(self):
        return Artist.objects.prefetch_related(
            Prefetch("tags", queryset=Tag.objects.order_by("sort_order", "name"))
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        artist = cast(Artist, self.get_object())
        ctx["artist_tags"] = list(artist.tags.all())

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
# Tags
# -----------------------------------------------------------------------------

class TagListView(TemplateView):
    template_name = "catalog/tag_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        media_tags = (
            Tag.objects.filter(scope=Tag.Scope.MEDIA_ITEM)
            .annotate(
                item_count=Count("media_items", distinct=True),
                artist_count=Count("media_items__artist", distinct=True),
            )
            .order_by("sort_order", "name")
        )

        artist_tags = (
            Tag.objects.filter(scope=Tag.Scope.ARTIST)
            .annotate(
                artist_count=Count("artists", distinct=True),
                item_count=Count("artists__media_items", distinct=True),
            )
            .order_by("sort_order", "name")
        )

        ctx["media_tags"] = media_tags
        ctx["artist_tags"] = artist_tags
        return ctx


class TagDetailView(CatalogListView):
    """
    Reuse the Records list UI (filters + pagination), scoped to a tag.
    """

    def dispatch(self, request, *args, **kwargs):
        self.tag = Tag.objects.get(pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()

        if self.tag.scope == Tag.Scope.MEDIA_ITEM:
            qs = qs.filter(tags=self.tag)
        else:
            qs = qs.filter(artist__tags=self.tag)

        return qs.distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["active_tag"] = self.tag
        ctx["list_url_name"] = "catalog_public:tag_detail"

        ctx["base_qs"] = _base_qs({
            "tag": self.tag.pk,
            "q": ctx["q"],
            "media": ctx["media"],
            "zone": ctx["zone"],
        })

        ctx["tag_item_count"] = ctx["page_obj"].paginator.count

        if self.tag.scope == Tag.Scope.MEDIA_ITEM:
            ctx["tag_artist_count"] = self.get_queryset().values("artist_id").distinct().count()
        else:
            ctx["tag_artist_count"] = Artist.objects.filter(tags=self.tag).distinct().count()

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
            .prefetch_related(Prefetch("tags", queryset=Tag.objects.order_by("sort_order", "name")))
        )

    def _filtered_ids(self):
        qs = (
            MediaItem.objects
            .select_related("artist", "media_type", "media_type__default_zone", "zone_override")
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
            qs = qs.filter(
                Q(zone_override__id=zone)
                | Q(zone_override__isnull=True, media_type__default_zone_id=zone)
            )

        return list(qs.values_list("id", flat=True)), q, media, zone

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        item = cast(MediaItem, self.get_object())
        ctx["item_tags"] = list(item.tags.all())

        ids, q, media, zone = self._filtered_ids()
        ctx["q"] = q
        ctx["media"] = media
        ctx["zone"] = zone

        ctx["back_query"] = f"?{_base_qs({'q': q, 'media': media, 'zone': zone})}"

        prev_id = next_id = None
        try:
            idx = ids.index(item.pk)
            if idx > 0:
                prev_id = ids[idx - 1]
            if idx < len(ids) - 1:
                next_id = ids[idx + 1]
        except ValueError:
            pass

        ctx["prev_id"] = prev_id
        ctx["next_id"] = next_id

        ctx["effective_zone"] = item.effective_zone
        ctx["default_zone"] = item.media_type.default_zone if item.media_type else None
        ctx["override_zone"] = item.zone_override

        return ctx
