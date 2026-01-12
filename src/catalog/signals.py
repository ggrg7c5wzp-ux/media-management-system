from __future__ import annotations

from typing import Optional, Set, Tuple, cast, Any

from django.db import transaction, models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from catalog.models import (
    Artist,
    BucketBinRange,
    LogicalBin,
    MediaItem,
    MediaType,
    RebinRun,
    SortBucket,
    StorageZone,
)

from catalog.services.binning import rebin_scope, rebin_zone

def _fk_id(obj: Any, attr: str) -> Optional[int]:
    """
    Safe FK id reader that won't blow up under typing when attrs differ or are deferred.
    Usage: _fk_id(item, "bucket_id"), _fk_id(item, "logical_bin_id"), _fk_id(item, "zone_override_id")
    """
    val = getattr(obj, attr, None)
    return cast(Optional[int], val)

# A "scope" means: (zone_id, bucket_id) where bucket_id may be None
Scope = Tuple[int, Optional[int]]


def _bucket_id(item: MediaItem) -> Optional[int]:
    return cast(Optional[int], getattr(item, "bucket_id", None))


def _zone_override_id(item: MediaItem) -> Optional[int]:
    return cast(Optional[int], getattr(item, "zone_override_id", None))


def _media_type_id(item: MediaItem) -> Optional[int]:
    return cast(Optional[int], getattr(item, "media_type_id", None))


def _effective_zone_id_for_item(item: MediaItem) -> int:
    """
    Effective zone:
      - zone_override wins
      - else media_type.default_zone
    Uses FK id columns when possible; falls back to a small query when needed.
    """
    zo = _zone_override_id(item)
    if zo:
        return int(zo)

    mt_obj = getattr(item, "media_type", None)
    if mt_obj is not None:
        return int(mt_obj.default_zone_id)

    mt_id = _media_type_id(item)
    if not mt_id:
        raise ValueError("MediaItem has no media_type; cannot determine effective zone")

    dz = (
        MediaType.objects.filter(pk=mt_id)
        .values_list("default_zone_id", flat=True)
        .first()
    )
    if not dz:
        raise ValueError(f"MediaType {mt_id} has no default_zone_id")
    return int(dz)


def _schedule_rebin(scopes: Set[Scope], *, notes: str) -> None:
    """
    Schedule one or more rebins after the current transaction commits.
    rebin_scope/rebin_zone will create RebinRun/RebinMove rows when record_moves=True.
    """

    def _run() -> None:
        if not scopes:
            return

        zone_ids = {zid for (zid, _bid) in scopes}
        zones_by_id = {z.pk: z for z in StorageZone.objects.filter(pk__in=zone_ids)}

        # If a zone is ALPHA_ONLY, bucket_id doesn't matter. Deduplicate per zone.
        alpha_only_done: Set[int] = set()

        for (zid, bid) in scopes:
            zone = zones_by_id.get(zid)
            if not zone or not zone.is_binned:
                continue

            # ALPHA_ONLY zones: one run per zone
            if zone.sort_strategy != StorageZone.SortStrategy.BUCKETED:
                if zid in alpha_only_done:
                    continue
                alpha_only_done.add(zid)

                rebin_scope(zone=zone, bucket_id=None, record_moves=True, notes=notes)
                continue

            # BUCKETED zones:
            # - if bid is None: rebin whole zone (all buckets + bucketless)
            # - else: rebin just that bucket scope
            if bid is None:
                rebin_zone(zone=zone, record_moves=True, notes=notes)
                continue

            rebin_scope(zone=zone, bucket_id=bid, record_moves=True, notes=notes)

    transaction.on_commit(_run)


# -----------------------------
# MediaItem signals
# -----------------------------

@receiver(pre_save, sender=MediaItem)
def mediaitem_presave(sender, instance: MediaItem, **kwargs) -> None:
    """
    Capture the old scope so post_save can rebin both old + new scopes if needed.
    """
    if not instance.pk:
        instance._old_scope = None  # type: ignore[attr-defined]
        return

    row = (
        MediaItem.objects.filter(pk=instance.pk)
        .values(
            "bucket_id",
            "zone_override_id",
            "media_type__default_zone_id",
        )
        .first()
    )
    if not row:
        instance._old_scope = None  # type: ignore[attr-defined]
        return

    old_zone_id = int(row["zone_override_id"] or row["media_type__default_zone_id"])
    old_bucket_id = cast(Optional[int], row["bucket_id"])
    instance._old_scope = (old_zone_id, old_bucket_id)  # type: ignore[attr-defined]


@receiver(post_save, sender=MediaItem)
def mediaitem_saved(sender, instance: MediaItem, **kwargs) -> None:
    """
    ANY save => rebin the smallest correct universe:
      - ALPHA_ONLY: zone-only
      - BUCKETED: (zone, bucket)
    Also rebin the old scope if it changed.
    """
    zone_id = _effective_zone_id_for_item(instance)
    bid = _bucket_id(instance)

    scopes: Set[Scope] = set()

    zone = instance.effective_zone
    if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
        scopes.add((zone_id, bid))
        if bid is None:
            scopes.add((zone_id, None))
    else:
        scopes.add((zone_id, None))

    old_scope = cast(Optional[Scope], getattr(instance, "_old_scope", None))
    if old_scope and old_scope != (zone_id, bid):
        old_zone_id, old_bid = old_scope
        old_zone = StorageZone.objects.filter(pk=old_zone_id).first()
        if old_zone:
            if old_zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
                scopes.add((old_zone_id, old_bid))
                if old_bid is None:
                    scopes.add((old_zone_id, None))
            else:
                scopes.add((old_zone_id, None))

    _schedule_rebin(scopes, notes="MediaItem saved")


@receiver(post_delete, sender=MediaItem)
def mediaitem_deleted(sender, instance: MediaItem, **kwargs) -> None:
    """
    ANY delete => rebin the relevant scope.
    """
    zone_id = _effective_zone_id_for_item(instance)
    bid = _bucket_id(instance)

    zone = instance.effective_zone
    scopes: Set[Scope] = set()

    if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
        scopes.add((zone_id, bid))
        if bid is None:
            scopes.add((zone_id, None))
    else:
        scopes.add((zone_id, None))

    _schedule_rebin(scopes, notes="MediaItem deleted")


# -----------------------------
# Artist signals
# -----------------------------

@receiver(post_save, sender=Artist)
def artist_saved(sender, instance: Artist, **kwargs) -> None:
    """
    ANY save to Artist => REBIN all scopes that contain:
      - this artist's items
      - PLUS items for any artists that file under this artist
        (because Artist.save() updates them via queryset.update(), which bypasses signals)
    """

    # Artists that may have had stored sort_name/alpha_bucket changed
    affected_artist_ids = list(
        Artist.objects.filter(
            models.Q(pk=instance.pk) | models.Q(filed_under_artist=instance)
        ).values_list("pk", flat=True)
    )

    items = (
        MediaItem.objects.filter(artist_id__in=affected_artist_ids)
        .select_related("media_type__default_zone", "zone_override", "bucket")
        .only("pk", "bucket_id", "zone_override_id", "media_type_id")
    )

    scopes: Set[Scope] = set()
    for it in items:
        zid = _effective_zone_id_for_item(it)
        bid = _bucket_id(it)
        zone = it.effective_zone

        if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
            scopes.add((zid, bid))
            if bid is None:
                scopes.add((zid, None))
        else:
            scopes.add((zid, None))

    _schedule_rebin(scopes, notes="Artist saved (incl filed-under dependents)")



# -----------------------------
# StorageZone capacity changes
# -----------------------------

@receiver(pre_save, sender=StorageZone)
def storagezone_presave(sender, instance: StorageZone, **kwargs) -> None:
    if not instance.pk:
        instance._old_default_bin_capacity = None  # type: ignore[attr-defined]
        return

    old = (
        StorageZone.objects.filter(pk=instance.pk)
        .values_list("default_bin_capacity", flat=True)
        .first()
    )
    instance._old_default_bin_capacity = old  # type: ignore[attr-defined]


@receiver(post_save, sender=StorageZone)
def storagezone_postsav(sender, instance: StorageZone, **kwargs) -> None:
    old = cast(Optional[int], getattr(instance, "_old_default_bin_capacity", None))
    new = instance.default_bin_capacity
    if old == new:
        return
    if not instance.is_binned:
        return

    _schedule_rebin({(cast(int, instance.pk), None)}, notes="StorageZone default_bin_capacity changed")


# -----------------------------
# LogicalBin capacity override changes
# -----------------------------

@receiver(pre_save, sender=LogicalBin)
def logicalbin_presave(sender, instance: LogicalBin, **kwargs) -> None:
    if not instance.pk:
        instance._old_capacity_override = None  # type: ignore[attr-defined]
        return
    old = (
        LogicalBin.objects.filter(pk=instance.pk)
        .values_list("capacity_override", flat=True)
        .first()
    )
    instance._old_capacity_override = old  # type: ignore[attr-defined]


@receiver(post_save, sender=LogicalBin)
def logicalbin_postsav(sender, instance: LogicalBin, **kwargs) -> None:
    old = cast(Optional[int], getattr(instance, "_old_capacity_override", None))
    new = instance.capacity_override
    if old == new:
        return

    zone_id = int(instance.zone.pk)
    _schedule_rebin({(zone_id, None)}, notes="LogicalBin capacity_override changed")
