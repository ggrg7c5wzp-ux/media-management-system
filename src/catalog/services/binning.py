from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.db.models import Q

from catalog.models import BucketBinRange, LogicalBin, MediaItem, StorageZone


GARAGE_MAIN_CODE = "GARAGE_MAIN"


@dataclass(frozen=True)
class AssignmentResult:
    logical_bin: Optional[LogicalBin]
    reason: str


def _effective_zone_filter(zone: StorageZone) -> Q:
    """
    Approximate 'effective zone' using stored fields:
    - if zone_override is set, that wins
    - otherwise media_type.default_zone
    """
    return Q(zone_override=zone) | (Q(zone_override__isnull=True) & Q(media_type__default_zone=zone))


def _garage_main_assign(media_item: MediaItem) -> AssignmentResult:
    zone = media_item.effective_zone

    if not media_item.bucket:
        return AssignmentResult(None, "No bucket set for Garage Main item")

    try:
        r = BucketBinRange.objects.get(zone=zone, bucket=media_item.bucket, is_active=True)
    except BucketBinRange.DoesNotExist:
        return AssignmentResult(None, "No BucketBinRange defined for (zone, bucket)")

    bins = list(
        LogicalBin.objects.filter(
            zone=zone,
            number__gte=r.start_bin,
            number__lte=r.end_bin,
            is_active=True,
        ).order_by("number")
    )
    if not bins:
        return AssignmentResult(None, "No logical bins exist in the allowed range")

    items = list(
        MediaItem.objects.filter(_effective_zone_filter(zone), bucket=media_item.bucket)
        .select_related("artist", "media_type", "zone_override", "bucket")
        .order_by("artist__sort_name", "title", "id")
    )

    # Ensure the item participates in deterministic ranking
    if media_item.pk is None:
        # New unsaved item: can't rank reliably
        return AssignmentResult(None, "MediaItem must be saved before assignment")

    if media_item not in items:
        items.append(media_item)
        items.sort(key=lambda x: (x.artist.sort_name, x.title, x.id))

    idx = items.index(media_item)

    # Capacity is not implemented yet, so we "pack" by rank -> bin index.
    bin_idx = min(idx, len(bins) - 1)
    chosen = bins[bin_idx]

    return AssignmentResult(chosen, f"GarageMain rank {idx} in bucket range {r.start_bin}-{r.end_bin}")


def _simple_zone_assign(media_item: MediaItem) -> AssignmentResult:
    """
    For zones without bucket ranges (Office/Turntable),
    do simple alpha fill across that zone's bins, ignoring bucket.
    """
    zone = media_item.effective_zone

    bins = list(LogicalBin.objects.filter(zone=zone, is_active=True).order_by("number"))
    if not bins:
        return AssignmentResult(None, "No logical bins exist in zone")

    items = list(
        MediaItem.objects.filter(_effective_zone_filter(zone))
        .select_related("artist", "media_type", "zone_override", "bucket")
        .order_by("artist__sort_name", "title", "id")
    )

    if media_item.pk is None:
        return AssignmentResult(None, "MediaItem must be saved before assignment")

    idx = items.index(media_item) if media_item in items else 0
    bin_idx = min(idx, len(bins) - 1)
    chosen = bins[bin_idx]

    return AssignmentResult(chosen, f"SimpleZone alpha rank {idx} across zone bins")


@transaction.atomic
def assign_logical_bin(media_item: MediaItem, *, persist: bool = True) -> AssignmentResult:
    zone_code = media_item.effective_zone.code

    if zone_code == GARAGE_MAIN_CODE:
        result = _garage_main_assign(media_item)
    else:
        result = _simple_zone_assign(media_item)

    if persist and result.logical_bin:
        if media_item.logical_bin_id != result.logical_bin.id:
            media_item.logical_bin = result.logical_bin
            media_item.save(update_fields=["logical_bin"])

    return result
