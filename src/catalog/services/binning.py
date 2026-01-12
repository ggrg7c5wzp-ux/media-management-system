from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, cast

from django.db import transaction
from django.db.models import Q

from catalog.models import (
    BucketBinRange,
    LogicalBin,
    MediaItem,
    RebinMove,
    RebinRun,
    SortBucket,
    StorageZone,
)

# =============================================================================
# Public API
# =============================================================================


@dataclass(frozen=True)
class AssignmentResult:
    logical_bin: Optional[LogicalBin]
    reason: str


def assign_logical_bin(media_item: MediaItem, *, persist: bool = True) -> AssignmentResult:
    """
    Assign exactly one MediaItem to a LogicalBin based on its *effective* zone rules.

    - BUCKETED zones: (zone, bucket) defines the universe via BucketBinRange.
    - ALPHA_ONLY zones: bucket ignored; rank is within effective zone.

    If persist=True, this updates ONLY MediaItem.logical_bin (no save()).
    """
    if media_item.pk is None:
        return AssignmentResult(None, "MediaItem must be saved before assignment")

    zone = media_item.effective_zone
    if zone is None:
        return AssignmentResult(None, "MediaItem has no effective zone")

    if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
        result = _bucketed_zone_assign(media_item)
    else:
        result = _alpha_only_zone_assign(media_item)

    if persist and result.logical_bin is not None:
        current_lb_id = cast(Optional[int], getattr(media_item, "logical_bin_id", None))
        desired_id = cast(int, result.logical_bin.pk)
        if current_lb_id != desired_id:
            # avoid save() side effects/signals; only touch the FK column
            MediaItem.objects.filter(pk=media_item.pk).update(logical_bin=result.logical_bin)
            # keep in-memory object coherent (and keep type checkers calm)
            setattr(media_item, "logical_bin", result.logical_bin)

    return result


def rebin_scope(
    *,
    zone: StorageZone,
    bucket_id: Optional[int] = None,
    record_moves: bool = False,
    notes: str = "",
) -> Optional[RebinRun]:
    """
    Re-evaluate placement for the smallest correct universe.

    - BUCKETED: scope is (zone, bucket_id). bucket_id may be None for the "bucketless" scope.
    - ALPHA_ONLY: scope is zone-only; bucket_id ignored.

    If record_moves=True, creates RebinRun + RebinMove rows for actual bin changes.
    """
    if zone.sort_strategy != StorageZone.SortStrategy.BUCKETED:
        bucket_id = None  # ignore in alpha-only zones

    with transaction.atomic():
        run: Optional[RebinRun] = None
        if record_moves:
            run = RebinRun.objects.create(
                zone=zone,
                bucket_id=bucket_id if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED else None,
                notes=notes,
            )

        items = list(_items_in_scope(zone=zone, bucket_id=bucket_id))
        if not items:
            return run

        bins, _bins_reason = _logical_bins_for_scope(zone=zone, bucket_id=bucket_id)
        if not bins:
            return run

        updated_items: list[MediaItem] = []
        moves_to_create: list[RebinMove] = []

        for idx, it in enumerate(items):
            chosen = _choose_bin_by_capacity(zone, bins, idx)
            if chosen is None:
                continue

            old_lb = cast(Optional[LogicalBin], getattr(it, "logical_bin", None))
            old_lb_id = cast(Optional[int], getattr(it, "logical_bin_id", None))
            chosen_id = cast(int, chosen.pk)

            if old_lb_id != chosen_id:
                setattr(it, "logical_bin", chosen)
                updated_items.append(it)

                if record_moves and run is not None:
                    moves_to_create.append(
                        RebinMove(
                            run=run,
                            media_item=it,
                            old_logical_bin=old_lb,
                            new_logical_bin=chosen,
                            old_physical_bin_label=_physical_label_for_logical(old_lb),
                            new_physical_bin_label=_physical_label_for_logical(chosen),
                        )
                    )

        if updated_items:
            MediaItem.objects.bulk_update(updated_items, ["logical_bin"])

        if record_moves and run is not None and moves_to_create:
            RebinMove.objects.bulk_create(moves_to_create)

        return run


def rebin_zone(*, zone: StorageZone, record_moves: bool = False, notes: str = "") -> list[Optional[RebinRun]]:
    """
    Rebin an entire StorageZone.
    - BUCKETED: rebin each active bucket + the bucketless scope.
    - ALPHA_ONLY: single zone-only rebin.
    """
    runs: list[Optional[RebinRun]] = []

    if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
        bucket_ids = list(SortBucket.objects.filter(is_active=True).values_list("pk", flat=True))
        bucket_ids.append(None)  # bucketless deterministic scope

        for bid in bucket_ids:
            runs.append(rebin_scope(zone=zone, bucket_id=bid, record_moves=record_moves, notes=notes))
    else:
        runs.append(rebin_scope(zone=zone, bucket_id=None, record_moves=record_moves, notes=notes))

    return runs


# =============================================================================
# Internals
# =============================================================================


def _items_in_scope(*, zone: StorageZone, bucket_id: Optional[int]) -> Iterable[MediaItem]:
    qs = MediaItem.objects.filter(_effective_zone_filter(zone))

    if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
        qs = qs.filter(bucket_id=bucket_id)

    # IMPORTANT: deterministic ordering uses stored artist.sort_name
    # (Your Artist.save() should make sort_name reflect "file under" when set.)
    return (
        qs.select_related("artist", "media_type", "zone_override", "bucket", "logical_bin")
        .order_by("artist__sort_name", "title", "pk")
    )


def _logical_bins_for_scope(*, zone: StorageZone, bucket_id: Optional[int]) -> tuple[Sequence[LogicalBin], str]:
    if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
        if bucket_id is None:
            bins = list(LogicalBin.objects.filter(zone=zone, is_active=True).order_by("number"))
            return bins, f"{zone.code} all bins (bucketless)"

        r = (
            BucketBinRange.objects.filter(zone=zone, bucket_id=bucket_id, is_active=True)
            .order_by("-pk")
            .first()
        )
        if not r:
            return [], f"{zone.code} bucket={bucket_id} (no BucketBinRange)"

        bins = list(
            LogicalBin.objects.filter(
                zone=zone,
                is_active=True,
                number__gte=r.start_bin,
                number__lte=r.end_bin,
            ).order_by("number")
        )
        return bins, f"{zone.code} bucket={bucket_id} bins {r.start_bin}-{r.end_bin}"

    bins = list(LogicalBin.objects.filter(zone=zone, is_active=True).order_by("number"))
    return bins, f"{zone.code} alpha-only all bins"


def _choose_bin_by_capacity(zone: StorageZone, bins: Sequence[LogicalBin], idx: int) -> Optional[LogicalBin]:
    if not bins:
        return None

    remaining = idx
    for b in bins:
        cap = b.effective_capacity
        if remaining < cap:
            return b
        remaining -= cap

    # deterministic overflow: pin to last bin
    return bins[-1]


def _bucketed_zone_assign(media_item: MediaItem) -> AssignmentResult:
    zone = media_item.effective_zone
    if zone is None:
        return AssignmentResult(None, "No effective zone")

    bucket_id = cast(Optional[int], getattr(media_item, "bucket_id", None))

    if bucket_id is None:
        bins, reason = _logical_bins_for_scope(zone=zone, bucket_id=None)
        items = list(_items_in_scope(zone=zone, bucket_id=None))
    else:
        bins, reason = _logical_bins_for_scope(zone=zone, bucket_id=bucket_id)
        items = list(_items_in_scope(zone=zone, bucket_id=bucket_id))

    if not bins:
        return AssignmentResult(None, f"No logical bins exist for scope: {reason}")

    if media_item not in items:
        items.append(media_item)
        items.sort(key=lambda x: (x.artist.sort_name, x.title, cast(int, x.pk)))

    idx = items.index(media_item)
    chosen = _choose_bin_by_capacity(zone, bins, idx)
    if not chosen:
        return AssignmentResult(None, f"Overflow: rank {idx} exceeds capacity in [{reason}]")

    return AssignmentResult(chosen, f"Bucketed rank {idx} in scope [{reason}] (capacity-aware)")


def _alpha_only_zone_assign(media_item: MediaItem) -> AssignmentResult:
    zone = media_item.effective_zone
    if zone is None:
        return AssignmentResult(None, "No effective zone")

    bins, reason = _logical_bins_for_scope(zone=zone, bucket_id=None)
    if not bins:
        return AssignmentResult(None, f"No logical bins exist for scope: {reason}")

    items = list(_items_in_scope(zone=zone, bucket_id=None))
    if media_item not in items:
        items.append(media_item)
        items.sort(key=lambda x: (x.artist.sort_name, x.title, cast(int, x.pk)))

    idx = items.index(media_item)
    chosen = _choose_bin_by_capacity(zone, bins, idx)
    if not chosen:
        return AssignmentResult(None, f"Overflow: rank {idx} exceeds capacity in [{reason}]")

    return AssignmentResult(chosen, f"Alpha-only rank {idx} in zone [{zone.code}] (capacity-aware)")


def _effective_zone_filter(zone: StorageZone) -> Q:
    """
    Effective zone:
      - zone_override wins
      - else media_type.default_zone
    """
    return Q(zone_override=zone) | (Q(zone_override__isnull=True) & Q(media_type__default_zone=zone))


# =============================================================================
# Logging helpers (bin label lookups)
# =============================================================================


def _physical_label_for_logical(logical_bin: Optional[LogicalBin]) -> str:
    if not logical_bin:
        return ""

    # BinMapping is a OneToOneField with related_name="mapping"
    mapping = getattr(logical_bin, "mapping", None)
    if not mapping or not getattr(mapping, "is_active", False):
        return ""

    pb = getattr(mapping, "physical_bin", None)
    return str(pb) if pb else ""
