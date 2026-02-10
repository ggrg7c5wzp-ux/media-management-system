# src/catalog/views.py

from __future__ import annotations

import datetime

from collections import Counter
from typing import cast
from urllib.parse import urlencode


from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpRequest, HttpResponse
from django.db.models import Q, Count, Prefetch
from django.views.generic import ListView, DetailView, TemplateView

from .models import Artist, MediaItem, StorageZone, MediaType, SortBucket, Tag


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

        ctx["counts"] = {
            "artists": Artist.objects.count(),
            "items": MediaItem.objects.count(),
        }

        # Genre (Sort Buckets)
        ctx["buckets"] = (
            SortBucket.objects.filter(is_active=True)
            .annotate(item_count=Count("media_items", distinct=True))
            .order_by("sort_order", "name")
        )

        # Media Types
        ctx["media_types"] = (
            MediaType.objects.all()
            .annotate(item_count=Count("media_items", distinct=True))
            .order_by("name")
        )

        return ctx


# -----------------------------------------------------------------------------
# Catalog list (Records table)

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
                "logical_bin__mapping",
                "logical_bin__mapping__physical_bin",
                "logical_bin__mapping__physical_bin__zone",
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
                "logical_bin__mapping",
                "logical_bin__mapping__physical_bin",
                "logical_bin__mapping__physical_bin__zone",
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
# Genre (Sort Buckets) and Media Types
# -----------------------------------------------------------------------------

class GenreListView(TemplateView):
    template_name = "catalog/genre_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["buckets"] = (
            SortBucket.objects.filter(is_active=True)
            .annotate(item_count=Count("media_items", distinct=True))
            .order_by("sort_order", "name")
        )
        return ctx


class GenreDetailView(CatalogListView):
    """Reuse the catalog table UI scoped to a SortBucket."""

    def dispatch(self, request, *args, **kwargs):
        self.bucket = SortBucket.objects.get(pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(bucket=self.bucket)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_bucket"] = self.bucket
        return ctx


class MediaTypeListView(TemplateView):
    template_name = "catalog/media_type_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["media_types"] = (
            MediaType.objects.all()
            .annotate(item_count=Count("media_items", distinct=True))
            .order_by("name")
        )
        return ctx


class MediaTypeDetailView(CatalogListView):
    """Reuse the catalog table UI scoped to a MediaType."""

    def dispatch(self, request, *args, **kwargs):
        self.mt = MediaType.objects.get(pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(media_type=self.mt)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_media_type"] = self.mt
        # keep filter dropdown aligned
        ctx["media"] = str(self.mt.pk)
        return ctx


# -----------------------------------------------------------------------------
# Curated
# -----------------------------------------------------------------------------

class CuratedView(TemplateView):
    template_name = "catalog/curated.html"

    # url kwarg: key in {"cander","darvina","audiophile"}
    CANDIDATES = {
        "cander": {
            "title": "Cander’s Picks",
            "artist_slugs": ["canders-picks", "cander-picks", "mikes-picks", "mike-s-picks"],
            "media_slugs": ["canders-picks", "cander-picks", "mikes-picks", "mike-s-picks"],
        },
        "darvina": {
            "title": "Darvina’s Picks",
            "artist_slugs": ["darvinas-picks", "darvina-picks", "julies-picks", "julie-s-picks"],
            "media_slugs": ["darvinas-picks", "darvina-picks", "julies-picks", "julie-s-picks"],
        },
        "audiophile": {
            "title": "Audiophile Curated",
            "artist_slugs": [],
            "media_slugs": ["special", "premium-pressing", "box-set" ],
        },
    }

    def _first_tag(self, scope: str, slugs: list[str]) -> Tag | None:
        for s in slugs:
            t = Tag.objects.filter(scope=scope, slug=s).first()
            if t:
                return t
        return None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        key = str(self.kwargs.get("key") or "cander")
        spec = self.CANDIDATES.get(key) or self.CANDIDATES["cander"]

        ctx["title"] = spec["title"]



        # Special case: Audiophile is three stacked sections (Premium / Special / Box Set)
        if key == "audiophile":
            def _tag(slugs: list[str]) -> Tag | None:
                return self._first_tag(Tag.Scope.MEDIA_ITEM, slugs)

            sections_spec = [
                ("Special", _tag(["special"])),
                ("Premium", _tag(["premium-pressing"])),                
                ("Box Set", _tag(["box-set"])),
            ]

            media_base = (
                MediaItem.objects.select_related("artist", "media_type")
                .order_by("artist__sort_name", "title", "pk")
            )

            sections = []
            for title, tag in sections_spec:
                if tag:
                    items = media_base.filter(tags=tag).distinct()
                else:
                    items = MediaItem.objects.none()
                sections.append({"title": title, "tag": tag, "items": items})

            ctx["sections"] = sections
            ctx["is_audiophile"] = True
            ctx["artists"] = Artist.objects.none()
            ctx["items"] = MediaItem.objects.none()
            return ctx

        ctx["is_audiophile"] = False

        artist_tag = self._first_tag(Tag.Scope.ARTIST, spec["artist_slugs"])
        media_tag = self._first_tag(Tag.Scope.MEDIA_ITEM, spec["media_slugs"])

        ctx["artist_tag"] = artist_tag
        ctx["media_tag"] = media_tag

        if artist_tag:
            ctx["artists"] = (
                Artist.objects.filter(tags=artist_tag)
                .annotate(item_count=Count("media_items", distinct=True))
                .order_by("sort_name", "display_name")
            )
        else:
            ctx["artists"] = Artist.objects.none()

        media_qs = (
            MediaItem.objects.select_related("artist", "media_type")
            .order_by("artist__sort_name", "title", "pk")
        )

        if media_tag:
            media_qs = media_qs.filter(tags=media_tag).distinct()
        elif key == "audiophile":
            # If no tag match, keep empty rather than lying.
            media_qs = MediaItem.objects.none()

        ctx["items"] = media_qs
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


# ------------------------------------------------------------
# Reports (staff-only)
# ------------------------------------------------------------

class StaffOnlyMixin(LoginRequiredMixin, UserPassesTestMixin):
    request: HttpRequest
    def test_func(self):
        user = getattr(self.request, "user", None)
        return bool(user and user.is_staff)


class EarlyWarningView(StaffOnlyMixin, TemplateView):
    template_name = "catalog/reports_early_warning.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        zone_code = self.request.GET.get("zone", "GARAGE_MAIN")
        zone = StorageZone.objects.filter(code=zone_code).first()
        ctx["zone"] = zone
        ctx["zones"] = StorageZone.objects.order_by("code")
        if zone:
            from catalog.services.reports import early_warning_for_zone
            rows = early_warning_for_zone(zone=zone)
            ctx["rows"] = rows

            import json, logging
            logging.getLogger(__name__).info(
                "EARLY_WARNING sample row: %s",
                json.dumps(rows[0], default=str) if rows else "NO_ROWS",
            )
        else:
            ctx["rows"] = []

        return ctx


class ReportsLandingView(StaffOnlyMixin, TemplateView):
    """Staff-only hub so we don't rely on browser bookmarks."""
    template_name = "catalog/reports_index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Operational reports (not part of the printable "book")
        ctx["operational_reports"] = [
            {
                "title": "Early Warning",
                "desc": "Capacity remaining in the last-used logical bin per bucket, plus next-bin collision checks.",
                "url": "catalog_public:report_early_warning",
            },
            {
                "title": "First / Last by Physical Bin",
                "desc": "Per physical bin: first item, last item, and count (HTML view).",
                "url": "catalog_public:report_first_last",
            },
            {
                "title": "First / Last by Physical Bin (PDF)",
                "desc": "Printable PDF output of the First/Last report.",
                "url": "catalog_public:first_last_pdf",
            },
        ]

        # Catalog Book (print-first, PDF-ready)
        ctx["catalog_book"] = [
            {
                "title": "Standard LP Catalog (HTML)",
                "desc": "Printable-style page for the Standard LP section of the binder.",
                "url": "catalog_public:book_standard_lps",
            },
            {
                "title": "Standard LP Catalog (PDF)",
                "desc": "PDF output of the Standard LP catalog page.",
                "url": "catalog_public:book_standard_lps_pdf",
            },
        ]

        return ctx

class StandardLPCatalogBookView(StaffOnlyMixin, TemplateView):
    template_name = "catalog/book/standard_lp_catalog.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        mt = MediaType.objects.filter(name__iexact="Standard LP").first()

        qs = (
            MediaItem.objects
            .select_related(
                "artist",
                "media_type",
                "zone_override",
                "logical_bin",
                "logical_bin__mapping",
                "logical_bin__mapping__physical_bin",
                "logical_bin__mapping__physical_bin__zone",
            )
            .order_by("artist__sort_name", "title", "pressing_year", "pk")
        )

        if mt:
            qs = qs.filter(media_type=mt)

        ctx["items"] = qs
        ctx["book_title"] = "Standard LP Catalog"
        ctx["generated_on"] = datetime.datetime.now()
        ctx["media_type"] = mt

        return ctx

        
class FirstLastByBinView(StaffOnlyMixin, TemplateView):
    template_name = "catalog/reports_first_last.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        zone_code = self.request.GET.get("zone", "GARAGE_MAIN")
        zone = StorageZone.objects.filter(code=zone_code).first()
        ctx["zone"] = zone
        ctx["zones"] = StorageZone.objects.order_by("code")
        if zone:
            from catalog.services.reports import first_last_per_physical_bin

            ctx["rows"] = first_last_per_physical_bin(zone=zone)
        else:
            ctx["rows"] = []
        return ctx


class RebinPreviewPdfView(StaffOnlyMixin, TemplateView):
    """
    Generates a PDF listing the moves that *would* happen for a rebin, without writing to the DB.
    Query params:
      - zone=ZONE_CODE (default GARAGE_MAIN)
    """

    def get(self, request, *args, **kwargs):
        zone_code = request.GET.get("zone", "GARAGE_MAIN")
        zone = StorageZone.objects.filter(code=zone_code).first()
        if not zone:
            return HttpResponse("Unknown zone", status=404)

        from io import BytesIO

        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas

        from catalog.services.binning import preview_rebin_zone

        scopes = preview_rebin_zone(zone=zone)

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter
        x = 0.75 * inch
        y = height - 0.75 * inch

        def line(txt: str, dy: float = 12):
            nonlocal y
            c.drawString(x, y, txt[:120])
            y -= dy
            if y < 0.75 * inch:
                c.showPage()
                y = height - 0.75 * inch

        line(f"Rebin Preview (no DB writes) — {zone.name} [{zone.code}]")
        line(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        line("")

        total_moves = 0
        for scope_name, moves in scopes.items():
            total_moves += len(moves)
            line(f"Scope: {scope_name}  (moves: {len(moves)})")
            line("-" * 95)
            if not moves:
                line("  (no moves)")
                line("")
                continue

            for mv in moves:
                line(f"  {mv.artist} — {mv.title}")
                if mv.old_physical_bin or mv.new_physical_bin:
                    line(f"     {mv.old_physical_bin}  →  {mv.new_physical_bin}")
                else:
                    line(f"     {mv.old_logical_bin}  →  {mv.new_logical_bin}")
            line("")

        if total_moves == 0:
            line("No moves detected. (Everything is already placed deterministically.)")

        c.save()
        pdf = buf.getvalue()
        buf.close()

        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="rebin_preview_{zone.code}.pdf"'
        return resp
