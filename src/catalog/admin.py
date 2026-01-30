from __future__ import annotations

from typing import cast
from urllib import request
from urllib.parse import urlencode

from django.db import transaction
from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html
from django.utils.text import Truncator

from catalog.services.binning import assign_logical_bin, rebin_scope, rebin_zone

from .models import (
    Artist,
    ArtistTag,
    BinMapping,
    BucketBinRange,
    LogicalBin,
    MediaItem,
    MediaItemTag,
    MediaType,
    PhysicalBin,
    RebinMove,
    RebinRun,
    SortBucket,
    StorageZone,
    Tag,
)

# ============================================================
# Canonical ordering (single source of truth)
# ============================================================

ITEM_ORDERING = ("artist__sort_name", "title", "master_key", "pk")


def format_item_line(item: MediaItem | None) -> str:
    """Display: Artist Name — Album Title"""
    if not item:
        return ""
    artist = getattr(item, "artist", None)
    artist_name = getattr(artist, "display_name", None) or "(no artist)"
    title = getattr(item, "title", None) or ""
    return f"{artist_name} — {title}"


# ============================================================
# Inlines / Forms
# ============================================================


class MediaItemInline(admin.TabularInline):
    model = MediaItem
    fk_name = "artist"
    extra = 0
    can_delete = False
    show_change_link = True

    fields = (
        "title",
        "pressing_year",
        "release_year",
        "media_type",
        "physical_bin_display_inline",
        "bucket",
    )
    readonly_fields = fields
    autocomplete_fields = ("media_type", "bucket")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Physical bin")
    def physical_bin_display_inline(self, obj: MediaItem) -> str:
        pb = getattr(obj, "physical_bin", None)
        return str(pb) if pb else ""


class MediaItemAdminForm(forms.ModelForm):
    class Meta:
        model = MediaItem
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # UI-only label change (no model change)
        if "title" in self.fields:
            self.fields["title"].label = "Album Title"

        # Admin UX rules
        if "release_year" in self.fields:
            self.fields["release_year"].required = False
        if "pressing_year" in self.fields:
            self.fields["pressing_year"].required = False
        if "bucket" in self.fields:
            self.fields["bucket"].required = False


class ArtistTagInline(admin.TabularInline):
    model = ArtistTag
    extra = 0
    autocomplete_fields = ("tag",)

    fields = ("tag", "tag_note_preview")
    readonly_fields = ("tag_note_preview",)

    @admin.display(description="TagNote")
    def tag_note_preview(self, obj: ArtistTag) -> str:
        tag = getattr(obj, "tag", None)
        return getattr(tag, "tag_note", "") or ""

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Only offer ARTIST-scoped tags in this inline."""
        if db_field.name == "tag":
            kwargs["queryset"] = Tag.objects.filter(scope=Tag.Scope.ARTIST).order_by("sort_order", "name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class MediaItemTagInline(admin.TabularInline):
    model = MediaItemTag
    extra = 0
    autocomplete_fields = ("tag",)

    fields = ("tag", "tag_note_preview")
    readonly_fields = ("tag_note_preview",)

    @admin.display(description="TagNote")
    def tag_note_preview(self, obj: MediaItemTag) -> str:
        tag = getattr(obj, "tag", None)
        return getattr(tag, "tag_note", "") or ""

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Only offer MEDIA_ITEM-scoped tags in this inline."""
        if db_field.name == "tag":
            kwargs["queryset"] = Tag.objects.filter(scope=Tag.Scope.MEDIA_ITEM).order_by("sort_order", "name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ============================================================
# Filters
# ============================================================


class EffectiveZoneFilter(admin.SimpleListFilter):
    """Filter MediaItems by effective zone (zone_override else media_type.default_zone)."""

    title = "storage zone"
    parameter_name = "ezone"

    def lookups(self, request, model_admin):
        return [(z.pk, z.name) for z in StorageZone.objects.order_by("name")]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset

        try:
            zone_id = int(value)
        except ValueError:
            return queryset.none()

        return queryset.filter(
            Q(zone_override_id=zone_id)
            | (Q(zone_override__isnull=True) & Q(media_type__default_zone_id=zone_id))
        )


# ============================================================
# Artist
# ============================================================


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ("display_name", "media_item_count_display")
    list_filter = ("artist_type", "alpha_bucket", "tags")
    search_fields = ("artist_name_primary", "artist_name_secondary", "display_name", "sort_name")
    inlines = [ArtistTagInline, MediaItemInline]
    ordering = ("sort_name",)

    readonly_fields = ("add_media_item_link", "display_name", "sort_name", "alpha_bucket", "created_at", "updated_at")

    fieldsets = (
        (
            "Artist (data entry)",
            {
                "fields": (
                    "artist_type",
                    "artist_name_primary",
                    "artist_name_secondary",
                    "name_suffix",
                    "filed_under_artist",
                )
            },
        ),
        ("Quick actions", {"fields": ("add_media_item_link",)}), 
        ("Computed (read-only)", {"fields": ("display_name", "sort_name", "alpha_bucket")}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )
    
    @admin.display(description="Quick actions")
    def add_media_item_link(self, obj):
        if not obj or not obj.pk:
            return ""
        url = reverse("admin:catalog_mediaitem_add")
        # Preselect artist in the add form
        return format_html('<a class="button" href="{}?artist={}">+ Add media item for this artist</a>', url, obj.pk)
    
    @admin.display(description="Media count", ordering="media_item_count")
    def media_item_count_display(self, obj: Artist) -> int:
        return getattr(obj, "media_item_count", 0) or 0

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(media_item_count=Count("media_items"))


# ============================================================
# Zones / Media Types
# ============================================================


@admin.register(StorageZone)
class StorageZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_binned", "sort_strategy", "default_bin_capacity", "bins_per_shelf")
    search_fields = ("name", "code")
    actions = ["generate_rebin_task_list"]

    @admin.action(description="Generate Rebin Task List (record moves)")
    def generate_rebin_task_list(self, request, queryset):
        from catalog.services.binning import rebin_zone

        created = 0
        for zone in queryset:
            rebin_zone(zone=zone, record_moves=True, notes="Manual task list generation")
            created += 1

        self.message_user(request, f"Generated task list for {created} zone(s).", level=messages.SUCCESS)


@admin.register(MediaType)
class MediaTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "default_zone", "is_vinyl", "requires_speed")
    list_filter = ("default_zone", "is_vinyl", "requires_speed")
    search_fields = ("name",)


# ============================================================
# Physical Bin
# ============================================================


@admin.register(PhysicalBin)
class PhysicalBinAdmin(admin.ModelAdmin):
    list_display = (
        "zone",
        "linear_bin_number_display",
        "shelf_number",
        "bin_number",
        "effective_capacity_display",
        "first_item",
        "last_item",
        "view_items",
        "is_active",
    )
    list_filter = ("zone", "is_active")
    ordering = ("zone__code", "shelf_number", "bin_number")
    search_fields = ("zone__code", "zone__name", "label")

    readonly_fields = ("effective_capacity_display", "first_item", "last_item", "view_items")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "zone",
                    "shelf_number",
                    "bin_number",
                    "label",
                    "effective_capacity_display",
                    "is_active",
                    "view_items",
                    "first_item",
                    "last_item",
                )
            },
        ),
    )

    @admin.display(description="Effective capacity")
    def effective_capacity_display(self, obj: PhysicalBin) -> int:
        return obj.effective_capacity

    def _items_qs_for_physical_bin(self, obj: PhysicalBin):
        return (
            MediaItem.objects.filter(
                logical_bin__mapping__is_active=True,
                logical_bin__mapping__physical_bin=obj,
            )
            .select_related("artist")
        )

    @admin.display(description="First item")
    def first_item(self, obj: PhysicalBin) -> str:
        item = self._items_qs_for_physical_bin(obj).order_by(*ITEM_ORDERING).first()
        return format_item_line(item) if item else "(empty)"

    @admin.display(description="Last item")
    def last_item(self, obj: PhysicalBin) -> str:
        item = self._items_qs_for_physical_bin(obj).order_by(*ITEM_ORDERING).last()
        return format_item_line(item) if item else "(empty)"

    @admin.display(description="Items")
    def view_items(self, obj: PhysicalBin) -> str:
        url = reverse("admin:catalog_mediaitem_changelist")
        qs = urlencode({"pb": obj.pk})
        return format_html('<a href="{}?{}">View items in this bin</a>', url, qs)

    @admin.display(description="Bin #", ordering="shelf_number")
    def linear_bin_number_display(self, obj: PhysicalBin) -> int:
        return obj.linear_bin_number

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("zone")


# ============================================================
# Logical Bin
# ============================================================


@admin.register(LogicalBin)
class LogicalBinAdmin(admin.ModelAdmin):
    list_display = (
        "zone",
        "number",
        "item_count_display",
        "capacity_override",
        "effective_capacity_display",
        "is_active",
        "first_item",
        "last_item",
        "view_items",
    )
    list_filter = ("zone", "is_active")
    ordering = ("zone__code", "number")
    search_fields = ("zone__code", "zone__name")

    readonly_fields = ("effective_capacity_display", "item_count_display", "first_item", "last_item", "view_items")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "zone",
                    "number",
                    "capacity_override",
                    "effective_capacity_display",
                    "item_count_display",
                    "is_active",
                    "view_items",
                    "first_item",
                    "last_item",
                )
            },
        ),
    )

    @admin.display(description="Effective capacity")
    def effective_capacity_display(self, obj: LogicalBin) -> int:
        return obj.effective_capacity

    def _items_qs_for_logical_bin(self, obj: LogicalBin):
        return MediaItem.objects.filter(logical_bin=obj).select_related("artist")

    @admin.display(description="First item")
    def first_item(self, obj: LogicalBin) -> str:
        item = self._items_qs_for_logical_bin(obj).order_by(*ITEM_ORDERING).first()
        return format_item_line(item) if item else "(empty)"

    @admin.display(description="Last item")
    def last_item(self, obj: LogicalBin) -> str:
        item = self._items_qs_for_logical_bin(obj).order_by(*ITEM_ORDERING).last()
        return format_item_line(item) if item else "(empty)"

    @admin.display(description="Items")
    def view_items(self, obj: LogicalBin) -> str:
        url = reverse("admin:catalog_mediaitem_changelist")
        qs = urlencode({"lb": obj.pk})
        return format_html('<a href="{}?{}">View items in this logical bin</a>', url, qs)

    @admin.display(description="Items", ordering="media_item_count")
    def item_count_display(self, obj: LogicalBin) -> int:
        return getattr(obj, "media_item_count", 0) or 0

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("zone")
        return qs.annotate(media_item_count=Count("media_items"))


# ============================================================
# Bin Mapping
# ============================================================


@admin.register(BinMapping)
class BinMappingAdmin(admin.ModelAdmin):
    list_display = ("logical_bin", "physical_bin", "is_active")
    list_filter = ("is_active", "logical_bin__zone", "physical_bin__zone")
    search_fields = (
        "logical_bin__zone__code",
        "logical_bin__number",
        "physical_bin__zone__code",
        "physical_bin__label",
    )


# ============================================================
# Media Items
# ============================================================


class MediaItemActionForm(admin.helpers.ActionForm):
    # existing
    tag_to_apply = forms.ModelChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        label="Tag to apply",
    )

    # NEW: bulk media classification controls
    new_media_type = forms.ModelChoiceField(
        queryset=MediaType.objects.all().order_by("name"),
        required=False,
        label="New media type",
    )

    new_zone_override = forms.ModelChoiceField(
        queryset=StorageZone.objects.all().order_by("name"),
        required=False,
        label="New zone override",
        help_text="Optional. If set, overrides the media type's default zone.",
    )

    clear_zone_override = forms.BooleanField(
        required=False,
        label="Clear zone override",
        help_text="If checked, removes any override (item will use media type default zone).",
    )

    clear_logical_bin = forms.BooleanField(
        required=False,
        label="Clear placement (logical_bin)",
        help_text="If checked, clears logical_bin for selected items before rebins so placement is recalculated cleanly.",
    )

    rebin_whole_zone = forms.BooleanField(
        required=False,
        label="Rebin whole zone(s)",
        help_text="If checked, rebins entire affected zone(s) instead of per-bucket scopes (safer, fewer runs).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # keep your existing tag behavior
        field = cast(forms.ModelChoiceField, self.fields["tag_to_apply"])
        field.queryset = Tag.objects.filter(scope=Tag.Scope.MEDIA_ITEM).order_by("sort_order", "name")



@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    form = MediaItemAdminForm
    inlines = [MediaItemTagInline]

    action_form = MediaItemActionForm
    actions = ["recalculate_placement", "apply_tag_to_selected", "bulk_change_media_type_zone"]

    ordering = ITEM_ORDERING

    @admin.display(description="Artist", ordering="artist__sort_name")
    def artist_sorted(self, obj: MediaItem) -> str:
        artist = getattr(obj, "artist", None)
        return getattr(artist, "display_name", "") if artist else ""

    @admin.display(description="Album Title", ordering="title")
    def album_title(self, obj: MediaItem) -> str:
        return obj.title

    list_display = (
        "artist_sorted",
        "album_title",
        "release_year",
        "zone_display",
        "physical_bin_number_display",
        "media_type",
    )

    list_filter = (
        EffectiveZoneFilter,
        "media_type",
        "bucket",
        "owner",
        "tags",
    )

    search_fields = ("title", "artist__artist_name_primary", "artist__artist_name_secondary", "master_key")
    autocomplete_fields = ("artist", "media_type", "zone_override", "bucket")

    fieldsets = (
        ("Core info", {"fields": ("artist", "title", "owner", "release_year", "pressing_year")}),
        ("Classification inputs", {"fields": ("media_type", "bucket", "zone_override")}),
        ("Placement (read-only)", {"fields": ("master_key", "placement_status", "logical_bin", "physical_bin_display")}),
    )

    def changelist_view(self, request, extra_context=None):
        """Strip our private params (pb/lb) off the URL before admin lookups parse them."""
        req = cast(HttpRequest, request)
        setattr(req, "_pb", None)
        setattr(req, "_lb", None)

        if req.GET:
            q = req.GET.copy()
            pb = q.pop("pb", [None])[0]
            lb = q.pop("lb", [None])[0]
            setattr(req, "_pb", pb)
            setattr(req, "_lb", lb)
            req.GET = q

        return super().changelist_view(req, extra_context=extra_context)

    def get_queryset(self, request):
        qs = (
            super()
            .get_queryset(request)
            .select_related(
                "artist",
                "media_type",
                "bucket",
                "logical_bin",
                "media_type__default_zone",
                "zone_override",
                "logical_bin__mapping__physical_bin",
            )
        )

        pb = getattr(request, "_pb", None)
        lb = getattr(request, "_lb", None)

        if lb:
            try:
                lb_id = int(lb)
            except ValueError:
                return qs.none()
            qs = qs.filter(logical_bin_id=lb_id)

        if pb:
            try:
                pb_id = int(pb)
            except ValueError:
                return qs.none()
            qs = qs.filter(
                logical_bin__mapping__is_active=True,
                logical_bin__mapping__physical_bin_id=pb_id,
            )

        return qs

    @admin.display(description="Physical bin")
    def physical_bin_display(self, obj: MediaItem) -> str:
        pb = getattr(obj, "physical_bin", None)
        return str(pb) if pb else ""

    @admin.display(description="Placement")
    def placement_status(self, obj: MediaItem) -> str:
        if not obj.pk:
            return ""
        if not obj.logical_bin:
            return "UNASSIGNED"
        pb = getattr(obj, "physical_bin", None)
        if not pb:
            return f"{obj.logical_bin} (no physical mapping)"
        return f"{obj.logical_bin} → {pb}"

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        ro.extend(["placement_status", "physical_bin_display", "logical_bin"])
        return ro

    @admin.display(description="Zone")
    def zone_display(self, obj: MediaItem) -> str:
        zone = getattr(obj, "effective_zone", None)
        return zone.name if zone else ""

    @admin.display(description="Bin #")
    def physical_bin_number_display(self, obj: MediaItem):
        pb = getattr(obj, "physical_bin", None)
        return pb.linear_bin_number if pb else ""

    @admin.action(description="Recalculate placement (logical_bin)")
    def recalculate_placement(self, request, queryset):
        qs = queryset.select_related("artist", "media_type", "zone_override", "bucket")
        updated = 0
        scopes: set[tuple[int, int | None]] = set()

        for item in qs:
            zone = item.effective_zone
            if zone:
                if zone.sort_strategy == StorageZone.SortStrategy.BUCKETED:
                    scopes.add((zone.id, item.bucket_id))
                else:
                    scopes.add((zone.id, None))

            result = assign_logical_bin(item, persist=True)
            if getattr(result, "logical_bin", None):
                updated += 1

        notes = f"Manual admin placement recalculation (selected={qs.count()}, updated={updated})"

        created_runs = 0
        for zone_id, bucket_id in scopes:
            RebinRun.objects.create(zone_id=zone_id, bucket_id=bucket_id, notes=notes)
            created_runs += 1

        self.message_user(
            request,
            f"Recalculated placement for {updated} item(s). Logged {created_runs} rebin run(s).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Bulk change media type / zone override")
    def bulk_change_media_type_zone(self, request, queryset):
        """
        Bulk-edit MediaItem.media_type and optionally zone_override (set or clear),
        then rebin the affected scopes efficiently.

        NOTE: queryset.update() bypasses signals, so we explicitly rebin scopes.
        """
        new_media_type_id = request.POST.get("new_media_type") or ""
        new_zone_override_id = request.POST.get("new_zone_override") or ""
        clear_zone_override = request.POST.get("clear_zone_override") == "on"
        clear_logical_bin = request.POST.get("clear_logical_bin") == "on"
        rebin_whole_zone = request.POST.get("rebin_whole_zone") == "on"
        
        if not new_media_type_id and not new_zone_override_id and not clear_zone_override:
            self.message_user(
                request,
                "Pick a New media type and/or New zone override, or check Clear zone override.",
                level=messages.WARNING,
            )
            return

        # If both are provided, "clear" wins (less surprising)
        if clear_zone_override and new_zone_override_id:
            new_zone_override_id = ""

        item_ids = list(queryset.values_list("id", flat=True))
        if not item_ids:
            self.message_user(request, "No items selected.", level=messages.WARNING)
            return

        # Helper: compute scope list from rows shaped like:
        # {bucket_id, zone_override_id, media_type__default_zone_id}
        def scopes_from_rows(rows, *, rebin_whole_zone: bool):
            """
            Return a set of scopes to rebin.
            If rebin_whole_zone=True, returns (zone_id, None) only (zone-level rebins).
            Otherwise returns bucket-aware scopes (zone_id, bucket_id).
            """
            scopes = set()
            
            zone_ids = {int(r["zone_override_id"] or r["media_type__default_zone_id"]) for r in rows}
            zones = {
                int(z.pk): z
                for z in StorageZone.objects.filter(pk__in=zone_ids).only("pk", "is_binned", "sort_strategy")
            }
            
            alpha_only_done = set()

            for r in rows:
                zone_id = int(r["zone_override_id"] or r["media_type__default_zone_id"])
                bucket_id = r["bucket_id"]

                zone = zones.get(zone_id)
                if not zone or not zone.is_binned:
                    continue

                # If user asked for whole-zone rebins, we only need zone-level scopes.
                if rebin_whole_zone:
                    scopes.add((zone_id, None))
                    continue

                if zone.sort_strategy != StorageZone.SortStrategy.BUCKETED:
                    if zone_id in alpha_only_done:
                        continue
                    alpha_only_done.add(zone_id)
                    scopes.add((zone_id, None))
                    continue
                
                scopes.add((zone_id, bucket_id))
                if bucket_id is None:
                    scopes.add((zone_id, None))

            return scopes


        with transaction.atomic():
            # 1) Capture old scopes
            old_rows = list(
                MediaItem.objects.filter(id__in=item_ids)
                .values("bucket_id", "zone_override_id", "media_type__default_zone_id")
            )
            old_scopes = scopes_from_rows(old_rows, rebin_whole_zone=rebin_whole_zone)

            # 2) Apply bulk update
            updates = {}

            if new_media_type_id:
                try:
                    updates["media_type_id"] = int(new_media_type_id)
                except ValueError:
                    self.message_user(request, "Invalid media type selection.", level=messages.ERROR)
                    return

            if clear_zone_override:
                updates["zone_override"] = None
            elif new_zone_override_id:
                try:
                    updates["zone_override_id"] = int(new_zone_override_id)
                except ValueError:
                    self.message_user(request, "Invalid zone override selection.", level=messages.ERROR)
                    return

            updated = queryset.update(**updates)
            
            if clear_logical_bin:
                MediaItem.objects.filter(id__in=item_ids).update(logical_bin=None)

            # 3) Capture new scopes
            new_rows = list(
                MediaItem.objects.filter(id__in=item_ids)
                .values("bucket_id", "zone_override_id", "media_type__default_zone_id")
            )
            new_scopes = scopes_from_rows(new_rows, rebin_whole_zone=rebin_whole_zone)

            scopes_to_rebin = old_scopes | new_scopes
            notes = f"Bulk media type/zone override change (selected={len(item_ids)}, updated={updated})"

            # 4) Rebin after commit (keeps DB state consistent)

            def _run_rebins():
                # If whole-zone, we only have (zone_id, None) pairs anyway—still safe to treat explicitly.
                zone_ids = {zone_id for (zone_id, _bucket_id) in scopes_to_rebin}

                for zone_id in zone_ids:
                    zone = StorageZone.objects.filter(pk=zone_id).first()
                    if not zone or not zone.is_binned:
                        continue

                    if rebin_whole_zone:
                        rebin_zone(zone=zone, record_moves=True, notes=notes)
                        continue

                    # bucket-aware mode: replay the exact scopes we computed
                    for (zid, bucket_id) in [s for s in scopes_to_rebin if s[0] == zone_id]:
                        if zone.sort_strategy != StorageZone.SortStrategy.BUCKETED:
                            rebin_scope(zone=zone, bucket_id=None, record_moves=True, notes=notes)
                        else:
                            if bucket_id is None:
                                rebin_zone(zone=zone, record_moves=True, notes=notes)
                            else:
                                rebin_scope(zone=zone, bucket_id=bucket_id, record_moves=True, notes=notes)      

            transaction.on_commit(_run_rebins)

        self.message_user(
            request,
            f"Updated {updated} item(s). Scheduled rebins for {len(scopes_to_rebin)} affected scope(s).",
            level=messages.SUCCESS,
        )


    @admin.action(description="Apply selected tag to selected media items")
    def apply_tag_to_selected(self, request, queryset):
        tag_id = request.POST.get("tag_to_apply")
        if not tag_id:
            self.message_user(request, "Pick a tag in 'Tag to apply' first.", level=messages.WARNING)
            return

        try:
            tag_id_int = int(tag_id)
        except ValueError:
            self.message_user(request, "Invalid tag selection.", level=messages.ERROR)
            return

        tag = Tag.objects.filter(id=tag_id_int, scope=Tag.Scope.MEDIA_ITEM).first()
        if not tag:
            self.message_user(request, "That tag is not a Media Item tag.", level=messages.ERROR)
            return

        media_item_ids = list(queryset.values_list("id", flat=True))
        tag_pk = cast(int, tag.pk)

        existing = set(
            MediaItemTag.objects.filter(media_item_id__in=media_item_ids, tag_id=tag_pk).values_list(
                "media_item_id", flat=True
            )
        )

        to_create = [MediaItemTag(media_item_id=mid, tag_id=tag_pk) for mid in media_item_ids if mid not in existing]

        if to_create:
            MediaItemTag.objects.bulk_create(to_create, ignore_conflicts=True)

        self.message_user(
            request,
            f"Applied tag '{tag.name}' to {len(media_item_ids)} media item(s). Added {len(to_create)} new link(s).",
            level=messages.SUCCESS,
        )


# ============================================================
# Buckets / Ranges / Rebin
# ============================================================


@admin.register(SortBucket)
class SortBucketAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    ordering = ("sort_order", "name")


@admin.register(BucketBinRange)
class BucketBinRangeAdmin(admin.ModelAdmin):
    list_display = ("zone", "bucket", "start_bin", "end_bin", "is_active")
    list_filter = ("zone", "is_active", "bucket")
    search_fields = ("zone__code", "bucket__name", "bucket__code")
    ordering = ("zone__code", "start_bin", "end_bin")


@admin.register(RebinMove)
class RebinMoveAdmin(admin.ModelAdmin):
    list_display = (
        "media_item_artist",
        "media_item",
        "old_location",
        "new_location",
        "run",
        "is_done",
        "created_at",
    )
    list_filter = ("is_done", "created_at", "run__zone", "run__bucket")
    search_fields = (
        "media_item__title",
        "media_item__artist__artist_name_primary",
        "old_physical_bin_label",
        "new_physical_bin_label",
    )
    actions = ["mark_done"]

    def _location_from_logical(self, lb: LogicalBin | None, fallback_label: str) -> str:
        if not lb:
            return fallback_label or "-"
        zone = getattr(lb, "zone", None)
        zone_name = zone.name if zone else ""
        mapping = getattr(lb, "mapping", None)
        pb = mapping.physical_bin if mapping and mapping.is_active else None
        if not pb:
            return fallback_label or f"{zone_name}: (unmapped)"
        return f"{zone_name} Bin {pb.linear_bin_number}"

    @admin.display(description="Old location")
    def old_location(self, obj: RebinMove) -> str:
        return self._location_from_logical(obj.old_logical_bin, obj.old_physical_bin_label)

    @admin.display(description="Artist", ordering="media_item__artist__sort_name")
    def media_item_artist(self, obj: RebinMove) -> str:
        mi = getattr(obj, "media_item", None)
        a = getattr(mi, "artist", None)
        return getattr(a, "display_name", "—")

    @admin.display(description="New location")
    def new_location(self, obj: RebinMove) -> str:
        return self._location_from_logical(obj.new_logical_bin, obj.new_physical_bin_label)

    @admin.action(description="Mark selected moves as done")
    def mark_done(self, request, queryset):
        queryset.update(is_done=True)


class RebinMoveInline(admin.TabularInline):
    model = RebinMove
    extra = 0
    can_delete = False
    fields = ("media_item", "old_physical_bin_label", "new_physical_bin_label", "is_done", "created_at")
    readonly_fields = ("media_item", "old_physical_bin_label", "new_physical_bin_label", "created_at")


@admin.register(RebinRun)
class RebinRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "zone", "bucket", "notes", "move_count", "open_count")
    readonly_fields = ("created_at",)
    inlines = [RebinMoveInline]

    @admin.display(description="Moves")
    def move_count(self, obj: RebinRun) -> int:
        moves = getattr(obj, "moves", None)
        return moves.count() if moves is not None else 0

    @admin.display(description="Open")
    def open_count(self, obj: RebinRun) -> int:
        moves = getattr(obj, "moves", None)
        return moves.filter(is_done=False).count() if moves is not None else 0


# ============================================================
# Tags
# ============================================================


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "scope",
        "sort_order",
        "slug",
        "tag_note_preview",
        "tagged_count",
        "view_tagged_objects",
    )
    list_filter = ("scope",)
    search_fields = ("name", "slug", "tag_note")
    ordering = ("scope", "sort_order", "name")
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # annotate counts by scope
        return qs.annotate(
            media_item_count=Count("media_item_tags", distinct=True),
            artist_count=Count("artist_tags", distinct=True),
        )

    @admin.display(description="TagNote")
    def tag_note_preview(self, obj: Tag) -> str:
        if not obj.tag_note:
            return ""
        return Truncator(obj.tag_note).chars(60)

    @admin.display(description="Tagged", ordering="media_item_count")
    def tagged_count(self, obj: Tag) -> int:
        if obj.scope == Tag.Scope.MEDIA_ITEM:
            return getattr(obj, "media_item_count", 0) or 0
        return getattr(obj, "artist_count", 0) or 0

    @admin.display(description="Open")
    def view_tagged_objects(self, obj: Tag) -> str:
        if obj.scope == Tag.Scope.MEDIA_ITEM:
            url = reverse("admin:catalog_mediaitem_changelist")
            # uses the built-in ManyToMany filter param name "tags__id__exact"
            qs = urlencode({"tags__id__exact": obj.pk})
            return format_html('<a href="{}?{}">View tagged media items</a>', url, qs)

        url = reverse("admin:catalog_artist_changelist")
        qs = urlencode({"tags__id__exact": obj.pk})
        return format_html('<a href="{}?{}">View tagged artists</a>', url, qs)

