from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from django.db.models import Q

try:
    # Optional dependency. The PDF view will raise a clear error if missing.
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    _HAS_REPORTLAB = True
except Exception:  # pragma: no cover
    canvas = None  # type: ignore[assignment]
    LETTER = None  # type: ignore[assignment]
    inch = None  # type: ignore[assignment]
    _HAS_REPORTLAB = False

from catalog.models import BucketBinRange, LogicalBin, MediaItem, PhysicalBin, SortBucket, StorageZone


def _effective_zone_filter(zone: StorageZone) -> Q:
    # MediaItem.effective_zone = zone_override OR media_type.default_zone
    return Q(zone_override=zone) | Q(zone_override__isnull=True, media_type__default_zone=zone)


@dataclass(frozen=True)
class EarlyWarningRow:
    bucket_name: str
    range_label: str
    last_used_bin: Optional[int]
    items_in_last_bin: int
    capacity_last_bin: Optional[int]
    remaining: Optional[int]
    next_bin: Optional[int]
    next_bin_within_range: bool
    next_bin_has_mapping: bool
    next_bin_range_conflicts: list[str]


def early_warning_for_zone(*, zone: StorageZone) -> list[EarlyWarningRow]:
    """
    For a BUCKETED zone, summarize remaining capacity in the *last-used* logical bin per bucket,
    and flag whether the *next* logical bin is safe to grow into.

    Notes:
    - This is a heuristic "heads up" report. It does not block rebins.
    - It uses current MediaItem.logical_bin assignments (so run a rebin first if needed).
    """
    if zone.sort_strategy != StorageZone.SortStrategy.BUCKETED:
        return []

    ranges = list(
        BucketBinRange.objects.filter(zone=zone, is_active=True)
        .select_related("bucket")
        .order_by("start_bin", "end_bin")
    )

    rows: list[EarlyWarningRow] = []
    for r in ranges:
        bucket = r.bucket
        bucket_name = bucket.name
        bucket_items = (
            MediaItem.objects.filter(_effective_zone_filter(zone), bucket=bucket, logical_bin__isnull=False)
            .select_related("logical_bin")
        )

        # determine last used bin number within this bucket's range
        last_num = (
            bucket_items.filter(logical_bin__number__gte=r.start_bin, logical_bin__number__lte=r.end_bin)
            .order_by("-logical_bin__number")
            .values_list("logical_bin__number", flat=True)
            .first()
        )

        if last_num is None:
            rows.append(
                EarlyWarningRow(
                    bucket_name=bucket_name,
                    range_label=f"{r.start_bin}-{r.end_bin}",
                    last_used_bin=None,
                    items_in_last_bin=0,
                    capacity_last_bin=None,
                    remaining=None,
                    next_bin=r.start_bin,
                    next_bin_within_range=True,
                    next_bin_has_mapping=_logical_bin_has_mapping(zone=zone, number=r.start_bin),
                    next_bin_range_conflicts=_range_conflicts(zone=zone, number=r.start_bin, bucket=bucket),
                )
            )
            continue

        items_in_last = bucket_items.filter(logical_bin__number=last_num).count()
        lb = LogicalBin.objects.filter(zone=zone, number=last_num).first()
        cap = lb.effective_capacity if lb else None
        remaining = (cap - items_in_last) if cap is not None else None

        next_num = int(last_num) + 1
        rows.append(
            EarlyWarningRow(
                bucket_name=bucket_name,
                range_label=f"{r.start_bin}-{r.end_bin}",
                last_used_bin=int(last_num),
                items_in_last_bin=items_in_last,
                capacity_last_bin=cap,
                remaining=remaining,
                next_bin=next_num,
                next_bin_within_range=(r.start_bin <= next_num <= r.end_bin),
                next_bin_has_mapping=_logical_bin_has_mapping(zone=zone, number=next_num),
                next_bin_range_conflicts=_range_conflicts(zone=zone, number=next_num, bucket=bucket),
            )
        )

    return rows


def _logical_bin_has_mapping(*, zone: StorageZone, number: int) -> bool:
    lb = LogicalBin.objects.filter(zone=zone, number=number).select_related("mapping").first()
    if not lb:
        return False
    mapping = getattr(lb, "mapping", None)
    return bool(mapping and mapping.is_active)


def _range_conflicts(*, zone: StorageZone, number: int, bucket: SortBucket) -> list[str]:
    """
    Return names of *other* buckets whose active ranges include this bin number.
    This is a lightweight "heads up" in case ranges ever overlap.
    """
    conflicts = (
        BucketBinRange.objects.filter(zone=zone, is_active=True, start_bin__lte=number, end_bin__gte=number)
        .exclude(bucket=bucket)
        .select_related("bucket")
    )
    return [c.bucket.name for c in conflicts]


@dataclass(frozen=True)
class FirstLastRow:
    physical_bin: str
    logical_bin: str
    linear_number: int
    first_item: str
    last_item: str
    count: int


def first_last_per_physical_bin(*, zone: StorageZone) -> list[FirstLastRow]:
    """
    For a binned zone, return (first,last,count) for each *physical* bin, based on the
    deterministic ordering used throughout the catalog.
    """
    if not zone.is_binned:
        return []

    # Pull all items for the zone in the canonical order.
    items = list(
        MediaItem.objects.filter(_effective_zone_filter(zone), logical_bin__isnull=False)
        .select_related("artist", "logical_bin")
        .order_by("logical_bin__number", "artist__sort_name", "title", "pk")
    )

    first_last_by_lb: dict[int, tuple[str, str, int]] = {}
    for it in items:
        lb = it.logical_bin
        if not lb:
            continue
        lb_num = int(lb.number)
        label = f"{it.artist.display_name} — {it.title}"
        if lb_num not in first_last_by_lb:
            first_last_by_lb[lb_num] = (label, label, 1)
        else:
            first, _last, cnt = first_last_by_lb[lb_num]
            first_last_by_lb[lb_num] = (first, label, cnt + 1)

    rows: list[FirstLastRow] = []
    pbs = (
        PhysicalBin.objects.filter(zone=zone, is_active=True)
        .select_related("zone")
        .prefetch_related("mappings__logical_bin")
        .order_by("shelf_number", "bin_number")
    )

    for pb in pbs:
        linear = (pb.shelf_number - 1) * zone.bins_per_shelf + pb.bin_number
        mapping = pb.mappings.filter(is_active=True).select_related("logical_bin").first()
        if not mapping or not mapping.logical_bin:
            rows.append(
                FirstLastRow(
                    physical_bin=str(pb),
                    logical_bin="",
                    linear_number=int(linear),
                    first_item="",
                    last_item="",
                    count=0,
                )
            )
            continue

        lb = mapping.logical_bin
        fl = first_last_by_lb.get(int(lb.number))
        if not fl:
            rows.append(
                FirstLastRow(
                    physical_bin=str(pb),
                    logical_bin=str(lb),
                    linear_number=int(linear),
                    first_item="",
                    last_item="",
                    count=0,
                )
            )
            continue

        first, last, cnt = fl
        rows.append(
            FirstLastRow(
                physical_bin=str(pb),
                logical_bin=str(lb),
                linear_number=int(linear),
                first_item=first,
                last_item=last,
                count=cnt,
            )
        )

    return rows


# -----------------------------------------------------------------------------
# Backwards/forwards-compatible aliases (so views can import without caring
# about exact naming).
# -----------------------------------------------------------------------------


def first_last_by_bin_for_zone(*, zone: StorageZone) -> list[FirstLastRow]:
    """Alias used by views."""
    return first_last_per_physical_bin(zone=zone)


def first_last_for_zone(*, zone: StorageZone) -> list[FirstLastRow]:
    """Alias used by views."""
    return first_last_per_physical_bin(zone=zone)


def render_rebin_preview_pdf(
    *,
    title: str,
    lines: Iterable[str],
    zone: Optional[StorageZone] = None,
) -> bytes:
    """Render a simple PDF with one line per row.

    The view/service computes the content; this function only renders.
    """
    if not _HAS_REPORTLAB or canvas is None or LETTER is None or inch is None:
        raise RuntimeError("ReportLab is not installed. Add it with: poetry add reportlab")

    if zone is not None:
        title = f"{title} — {zone.name or zone.code}"

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    _width, height = LETTER

    x = 0.75 * inch
    y = height - 0.75 * inch

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, title)
    y -= 0.35 * inch

    c.setFont("Helvetica", 10)
    line_height = 0.18 * inch

    for line in lines:
        if y < 0.75 * inch:
            c.showPage()
            y = height - 0.75 * inch
            c.setFont("Helvetica", 10)
        c.drawString(x, y, str(line)[:180])
        y -= line_height

    c.showPage()
    c.save()
    return buf.getvalue()


def rebin_preview_pdf_bytes(*, title: str, lines: Iterable[str], zone: Optional[StorageZone] = None) -> bytes:
    """Alias used by views."""
    return render_rebin_preview_pdf(title=title, lines=lines, zone=zone)
