from __future__ import annotations

from collections import defaultdict
import html
from urllib import request

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Case, When, F, IntegerField, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from weasyprint import HTML
from django.conf import settings
from pathlib import Path

from catalog.models import StorageZone, MediaItem, MediaType, Tag


# -----------------------------------------------------------------------------
# First/Last by Physical Bin (HTML + PDF)
# -----------------------------------------------------------------------------

def _first_last_by_physical_bin_rows(*, zone: StorageZone):
    qs = (
        MediaItem.objects
        .filter(Q(zone_override=zone) | Q(zone_override__isnull=True, media_type__default_zone=zone))
        .select_related(
            "artist",
            "media_type",
            "zone_override",
            "logical_bin",
            "logical_bin__mapping",
            "logical_bin__mapping__physical_bin",
            "logical_bin__mapping__physical_bin__zone",
        )
        .order_by("artist__sort_name", "title")
    )

    grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)

    for item in qs:
        pb = item.physical_bin
        if pb is None:
            pb_label = "UNMAPPED (no physical bin)"
            bin_sort = 10**9
        else:
            pb_label = str(pb)               # e.g. "GARAGE_MAIN: Shelf 1 Bin 7"
            bin_sort = pb.linear_bin_number  # physical order

        artist_name = (
            getattr(item.artist, "display_name", None)
            or getattr(item.artist, "artist_name_primary", "")
        )
        display = f"{artist_name} — {item.title}"

        grouped[pb_label].append((bin_sort, display))

    rows = []
    for pb_label, entries in grouped.items():
        entries.sort(key=lambda t: t[0])
        displays = [d for _, d in entries]
        rows.append({
            "physical_bin": pb_label,
            "first_item": displays[0] if displays else "",
            "last_item": displays[-1] if displays else "",
            "count": len(displays),
            "_bin_sort": entries[0][0] if entries else 10**9,
        })

    rows.sort(key=lambda r: r["_bin_sort"])
    for r in rows:
        r.pop("_bin_sort", None)
    return rows


def _get_first_last_context(*, zone_code: str | None) -> dict:
    zones = StorageZone.objects.order_by("code")

    # Prefer GARAGE_MAIN as the default zone
    default_zone = StorageZone.objects.filter(code="GARAGE_MAIN").first()

    if zone_code:
        zone = get_object_or_404(StorageZone, code=zone_code)
    else:
        zone = default_zone or zones.first()

    if zone is None:
        return {"zones": zones, "zone": None, "rows": []}

    rows = _first_last_by_physical_bin_rows(zone=zone)
    return {"zones": zones, "zone": zone, "rows": rows}


@staff_member_required
def first_last_by_physical_bin(request: HttpRequest) -> HttpResponse:
    """HTML report view."""
    context = _get_first_last_context(zone_code=request.GET.get("zone"))
    return render(request, "catalog/reports_first_last.html", context)


@staff_member_required
def first_last_by_physical_bin_pdf(request: HttpRequest) -> HttpResponse:
    """PDF version of the same report."""
    context = _get_first_last_context(zone_code=request.GET.get("zone"))

    html = render_to_string(
        "catalog/reports/first_last_by_physical_bin_pdf.html",
        context,
        request=request,
    )

    pdf_bytes = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="first_last_by_physical_bin.pdf"'
    return resp


# -----------------------------------------------------------------------------
# Catalog Book: Standard LP (PDF variants)
# -----------------------------------------------------------------------------

def _standard_lp_qs():
    """
    Returns (media_type, queryset) for Standard LP items.
    NOTE: relies on MediaType.name == "Standard LP" (case-insensitive).
    """
    mt = MediaType.objects.filter(name__iexact="Standard LP").first()
    garage_main = StorageZone.objects.filter(code="GARAGE_MAIN").first()

    qs = (
        MediaItem.objects
        .select_related(
            "artist",
            "media_type",
            "bucket",
            "zone_override",
            "logical_bin",
            "logical_bin__mapping",
            "logical_bin__mapping__physical_bin",
            "logical_bin__mapping__physical_bin__zone",
        )
        .annotate(
            effective_zone_id=Case(
                When(zone_override__isnull=False, then=F("zone_override_id")),
                default=F("media_type__default_zone_id"),
                output_field=IntegerField(),
            )
        )
        .order_by("artist__sort_name", "title", "pressing_year", "pk")
    )

    if mt:
        qs = qs.filter(media_type=mt)

    if garage_main is not None:
        qs = qs.filter(effective_zone_id=garage_main.pk)

    return mt, qs


def _pdf_response_from_template(
    *,
    request: HttpRequest,
    template_name: str,
    context: dict,
    filename: str,
) -> HttpResponse:
    html = render_to_string(template_name, context, request=request)
    static_root = getattr(settings, "STATIC_ROOT", None)
    base_url = Path(static_root).as_uri() + "/" if static_root else request.build_absolute_uri("/")
    pdf_bytes = HTML(string=html, base_url=base_url).write_pdf()

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp


@staff_member_required
def standard_lp_catalog_pdf(request: HttpRequest) -> HttpResponse:
    """All Standard LPs (PDF)."""
    mt, qs = _standard_lp_qs()

    context = {
        "items": qs,
        "book_title": "Garage LP Catalog",
        "generated_on": None,
        "media_type": mt,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/standard_lp_catalog.html",
        context=context,
        filename="standard_lp_catalog.pdf",
    )


# Adjust these bucket names to match your DB exactly if needed.
ROOTS_BUCKETS = ["Blues, Jazz, Vocals"]
SOUNDTRACK_BUCKETS = ["Soundtracks"]
MISC_BUCKETS = ["Compilations", "Holiday", "Miscellaneous"]
EXCLUDE_FOR_MAIN = ROOTS_BUCKETS + SOUNDTRACK_BUCKETS + MISC_BUCKETS

# This is used as the base template #

@staff_member_required
def standard_lp_catalog_main_pdf(request: HttpRequest) -> HttpResponse:
    """Standard LPs excluding Roots + Soundtracks + (Compilations/Holiday/Misc)."""
    mt, qs = _standard_lp_qs()
    qs = qs.exclude(bucket__name__in=EXCLUDE_FOR_MAIN)

    context = {
        "items": qs,
        "book_title": "Garage Standard LP Catalog",
        "generated_on": None,
        "media_type": mt,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/standard_lp_catalog.html",
        context=context,
        filename="standard_lp_catalog_main.pdf",
    )


@staff_member_required
def standard_lp_catalog_roots_pdf(request: HttpRequest) -> HttpResponse:
    """Standard LPs for Blues/Jazz/Vocals."""
    mt, qs = _standard_lp_qs()
    qs = qs.filter(bucket__name__in=ROOTS_BUCKETS)

    context = {
        "items": qs,
        "book_title": "Blue, Jazz, & Vocals",
        "generated_on": None,
        "media_type": mt,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/standard_lp_catalog.html",
        context=context,
        filename="standard_lp_catalog_blues.pdf",
    )


@staff_member_required
def standard_lp_catalog_soundtracks_pdf(request: HttpRequest) -> HttpResponse:
    """Standard LPs for Soundtracks."""
    mt, qs = _standard_lp_qs()
    qs = qs.filter(bucket__name__in=SOUNDTRACK_BUCKETS)

    context = {
        "items": qs,
        "book_title": "Soundtracks",
        "generated_on": None,
        "media_type": mt,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/standard_lp_catalog.html",
        context=context,
        filename="standard_lp_catalog_soundtracks.pdf",
    )


@staff_member_required
def standard_lp_catalog_misc_pdf(request: HttpRequest) -> HttpResponse:
    """Standard LPs for Compilations + Holiday + Miscellaneous."""
    mt, qs = _standard_lp_qs()
    qs = qs.filter(bucket__name__in=MISC_BUCKETS)

    context = {
        "items": qs,
        "book_title": "Miscellaneous",
        "generated_on": None,
        "media_type": mt,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/standard_lp_catalog.html",
        context=context,
        filename="standard_lp_catalog_misc.pdf",
    )



# -----------------------------------------------------------------------------
# Catalog Book: Curated / Mixed Sections (PDF)
# -----------------------------------------------------------------------------

PICKS_TAG_SLUG_CANDER = "canders-picks"
PICKS_TAG_SLUG_DARVINA = "darvinas-picks"
NEW_ADDITIONS_TAG_SLUG = "new-additions"

# NOTE: Premium Pressing is historically misspelled in some data as "Premium Pressimg".
AUDIOPHILE_TAG_SLUGS = [
    "special",
    "premium-pressing",
    "box-set",
]
AUDIOPHILE_TAG_NAME_FALLBACKS = [
    "Premium Pressing",
    "Premium Pressimg",
]

OTHER_MEDIA_TYPE_NAMES = [
    '7" Vinyl',
    "Cassette Tape",
    "CD",
]


def _book_base_qs():
    """Shared base queryset for book PDFs (kept intentionally simple)."""
    return (
        MediaItem.objects
        .select_related(
            "artist",
            "media_type",
            "media_type__default_zone",
            "bucket",
            "zone_override",
            "logical_bin",
            "logical_bin__mapping",
            "logical_bin__mapping__physical_bin",
            "logical_bin__mapping__physical_bin__zone",
        )
        .order_by("artist__sort_name", "title", "pressing_year", "pk")
    )


@staff_member_required
def curated_new_additions_pdf(request: HttpRequest) -> HttpResponse:
    """All media items with MediaItem tag = New Additions."""
    qs = _book_base_qs().filter(
        media_item_tags__tag__scope=Tag.Scope.MEDIA_ITEM,
        media_item_tags__tag__slug=NEW_ADDITIONS_TAG_SLUG,
    ).distinct()

    context = {
        "items": qs,
        "book_title": "New Additions",
        "generated_on": None,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/curated_catalog.html",
        context=context,
        filename="new_additions.pdf",
    )


@staff_member_required
def curated_canders_picks_pdf(request: HttpRequest) -> HttpResponse:
    """Media items where Artist tag OR MediaItem tag = Cander's Picks."""
    qs = _book_base_qs().filter(
        Q(artist__artist_tags__tag__scope=Tag.Scope.ARTIST, artist__artist_tags__tag__slug=PICKS_TAG_SLUG_CANDER)
        | Q(media_item_tags__tag__scope=Tag.Scope.MEDIA_ITEM, media_item_tags__tag__slug=PICKS_TAG_SLUG_CANDER)
    ).distinct()

    context = {
        "items": qs,
        "book_title": "Cander's Picks",
        "generated_on": None,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/curated_catalog.html",
        context=context,
        filename="canders_picks.pdf",
    )


@staff_member_required
def curated_darvinas_picks_pdf(request: HttpRequest) -> HttpResponse:
    """Media items where Artist tag OR MediaItem tag = Darvina's Picks."""
    qs = _book_base_qs().filter(
        Q(artist__artist_tags__tag__scope=Tag.Scope.ARTIST, artist__artist_tags__tag__slug=PICKS_TAG_SLUG_DARVINA)
        | Q(media_item_tags__tag__scope=Tag.Scope.MEDIA_ITEM, media_item_tags__tag__slug=PICKS_TAG_SLUG_DARVINA)
    ).distinct()

    context = {
        "items": qs,
        "book_title": "Darvina's Picks",
        "generated_on": None,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/curated_catalog.html",
        context=context,
        filename="darvinas_picks.pdf",
    )


@staff_member_required
def curated_audiophile_collection_pdf(request: HttpRequest) -> HttpResponse:
    """Audiophile collection: Special / Premium Pressing / Box Set (show zone, no bin)."""
    qs = _book_base_qs().filter(
        media_item_tags__tag__scope=Tag.Scope.MEDIA_ITEM,
    ).filter(
        Q(media_item_tags__tag__slug__in=AUDIOPHILE_TAG_SLUGS)
        | Q(media_item_tags__tag__name__in=AUDIOPHILE_TAG_NAME_FALLBACKS)
    ).distinct()

    context = {
        "items": qs,
        "book_title": "Audiophile Collection",
        "generated_on": None,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/audiophile_catalog.html",
        context=context,
        filename="audiophile_collection.pdf",
    )


@staff_member_required
def curated_other_media_pdf(request: HttpRequest) -> HttpResponse:
    """Other media: 7\" Vinyl, Cassette Tape, CD."""
    qs = _book_base_qs().filter(media_type__name__in=OTHER_MEDIA_TYPE_NAMES).distinct()

    context = {
        "items": qs,
        "book_title": "Other Media (7\" / Cassette / CD)",
        "generated_on": None,
        "hide_bin": True,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/other_media_catalog.html",
        context=context,
        filename="other_media.pdf",
    )
