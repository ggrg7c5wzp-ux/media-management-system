from __future__ import annotations

from collections import defaultdict

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from weasyprint import HTML

from catalog.models import StorageZone, MediaItem, MediaType


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
        .order_by("artist__sort_name", "title", "pressing_year", "pk")
    )

    if mt:
        qs = qs.filter(media_type=mt)

    return mt, qs


def _pdf_response_from_template(
    *,
    request: HttpRequest,
    template_name: str,
    context: dict,
    filename: str,
) -> HttpResponse:
    html = render_to_string(template_name, context, request=request)
    pdf_bytes = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp


@staff_member_required
def standard_lp_catalog_pdf(request: HttpRequest) -> HttpResponse:
    """All Standard LPs (PDF)."""
    mt, qs = _standard_lp_qs()

    context = {
        "items": qs,
        "book_title": "Standard LP Catalog",
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


@staff_member_required
def standard_lp_catalog_main_pdf(request: HttpRequest) -> HttpResponse:
    """Standard LPs excluding Roots + Soundtracks + (Compilations/Holiday/Misc)."""
    mt, qs = _standard_lp_qs()
    qs = qs.exclude(bucket__name__in=EXCLUDE_FOR_MAIN)

    context = {
        "items": qs,
        "book_title": "Standard LP Catalog — Main",
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
        "book_title": "Standard LP Catalog — Roots",
        "generated_on": None,
        "media_type": mt,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/standard_lp_catalog.html",
        context=context,
        filename="standard_lp_catalog_roots.pdf",
    )


@staff_member_required
def standard_lp_catalog_soundtracks_pdf(request: HttpRequest) -> HttpResponse:
    """Standard LPs for Soundtracks."""
    mt, qs = _standard_lp_qs()
    qs = qs.filter(bucket__name__in=SOUNDTRACK_BUCKETS)

    context = {
        "items": qs,
        "book_title": "Standard LP Catalog — Soundtracks",
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
        "book_title": "Standard LP Catalog — Misc",
        "generated_on": None,
        "media_type": mt,
    }
    return _pdf_response_from_template(
        request=request,
        template_name="catalog/book/standard_lp_catalog.html",
        context=context,
        filename="standard_lp_catalog_misc.pdf",
    )
