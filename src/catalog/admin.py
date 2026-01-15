from django.contrib import admin, messages
from django import forms

from .models import (
    StorageZone,
    MediaType,
    Artist,
    MediaItem,
    PhysicalBin,
    LogicalBin,
    BinMapping,
    SortBucket,
    BucketBinRange,
    RebinRun,
    RebinMove,
)

from catalog.services.binning import assign_logical_bin


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
        "physical_bin",
    )
    readonly_fields = fields
    autocomplete_fields = ("media_type", "bucket")


class MediaItemAdminForm(forms.ModelForm):
    class Meta:
        model = MediaItem
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Enforce required fields in Admin UI
        self.fields["release_year"].required = False
        self.fields["pressing_year"].required = True
        self.fields["bucket"].required = True


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
    )
    list_filter = ("artist_type", "alpha_bucket")
    search_fields = (
        "artist_name_primary",
        "artist_name_secondary",
        "display_name",
        "sort_name",
    )
    inlines = [MediaItemInline]
    ordering = ("sort_name",)

    readonly_fields = (
        "display_name",
        "sort_name",
        "alpha_bucket",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Artist (data entry)", {"fields": ("artist_type", "artist_name_primary", "artist_name_secondary", "name_suffix", "filed_under_artist")}),
        ("Computed (read-only)", {"fields": ("display_name", "sort_name", "alpha_bucket")}),
        ("System", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(StorageZone)
class StorageZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_binned", "sort_strategy", "default_bin_capacity")
    search_fields = ("name", "code")
    actions = ["generate_rebin_task_list"]

    @admin.action(description="Generate Rebin Task List (record moves)")
    def generate_rebin_task_list(self, request, queryset):
        from catalog.services.binning import rebin_zone

        created = 0
        for zone in queryset:
            rebin_zone(zone=zone, record_moves=True, notes="Manual task list generation")
            created += 1

        self.message_user(
            request,
            f"Generated task list for {created} zone(s).",
            level=messages.SUCCESS,
        )


@admin.register(MediaType)
class MediaTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "default_zone", "is_vinyl", "requires_speed")
    list_filter = ("default_zone", "is_vinyl", "requires_speed")
    search_fields = ("name",)


@admin.register(PhysicalBin)
class PhysicalBinAdmin(admin.ModelAdmin):
    list_display = ("zone", "shelf_number", "bin_number", "is_active")
    list_filter = ("zone", "is_active")
    ordering = ("zone__code", "shelf_number", "bin_number")
    search_fields = ("zone__code",)
    readonly_fields = ("effective_capacity",)

    fieldsets = (
        (None, {"fields": ("zone", "shelf_number", "bin_number", "label", "effective_capacity", "is_active")}),
    )

    def effective_capacity(self, obj):
        return obj.effective_capacity

    effective_capacity.short_description = "Effective capacity"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("mappings__logical_bin__zone")


@admin.register(LogicalBin)
class LogicalBinAdmin(admin.ModelAdmin):
    list_display = ("zone", "number", "capacity_override", "is_active")
    list_filter = ("zone", "is_active")
    ordering = ("zone__code", "number")
    search_fields = ("zone__code",)
    readonly_fields = ("effective_capacity",)

    fieldsets = (
        (None, {"fields": ("zone", "number", "capacity_override", "effective_capacity", "is_active")}),
    )

    def effective_capacity(self, obj):
        return obj.effective_capacity

    effective_capacity.short_description = "Effective capacity"


@admin.register(BinMapping)
class BinMappingAdmin(admin.ModelAdmin):
    list_display = ("logical_bin", "physical_bin", "is_active")
    list_filter = ("is_active", "logical_bin__zone")
    search_fields = (
        "logical_bin__zone__code",
        "logical_bin__number",
        "physical_bin__zone__code",
    )


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    # ---- List page ----
    list_display = (
        "artist",
        "title",
        "release_year",
        "media_type",
        "bucket",
        "placement_status",
        "physical_bin_display",
    )
    list_filter = ("media_type", "bucket", "owner", "media_type__default_zone")
    search_fields = ("title", "artist__artist_name_primary", "artist__artist_name_secondary", "master_key")
    autocomplete_fields = ("artist", "media_type", "zone_override", "bucket")

    # ---- Detail page layout ----
    fieldsets = (
        ("Core info", {"fields": ("artist", "title", "owner", "release_year", "pressing_year")}),
        ("Classification inputs", {"fields": ("media_type", "bucket", "zone_override")}),
        ("Placement (read-only)", {"fields": ("master_key", "placement_status", "logical_bin", "physical_bin_display")}),
    )

    form = MediaItemAdminForm

    # ---- Computed/derived fields for display ----
    def effective_zone_display(self, obj):
        return obj.effective_zone.name if obj.effective_zone else ""

    effective_zone_display.short_description = "Zone"

    def physical_bin_display(self, obj):
        pb = obj.physical_bin
        return str(pb) if pb else ""

    physical_bin_display.short_description = "Physical bin"

    def placement_status(self, obj):
        if not obj.pk:
            return ""
        if not obj.logical_bin:
            return "UNASSIGNED"
        pb = obj.physical_bin
        if not pb:
            return f"{obj.logical_bin} (no physical mapping)"
        return f"{obj.logical_bin} → {pb}"

    placement_status.short_description = "Placement"

    # ---- Read-only enforcement (engine owns placement) ----
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        ro.extend(["placement_status", "physical_bin_display"])
        ro.append("logical_bin")
        return ro

    # ---- Admin actions ----
    actions = ["recalculate_placement"]

    @admin.action(description="Recalculate placement (logical_bin)")
    def recalculate_placement(self, request, queryset):
        updated = 0
        for item in queryset.select_related("artist", "media_type", "zone_override", "bucket"):
            result = assign_logical_bin(item, persist=True)
            if result.logical_bin:
                updated += 1
        self.message_user(
            request,
            f"Recalculated placement for {updated} item(s).",
            level=messages.SUCCESS,
        )

    def save_model(self, request, obj, form, change):
        """
        Save only.

        Signals handle:
          - rebins (smallest correct universe)
          - RebinRun creation
          - RebinMove logging

        Keeping admin save_model free of move logging prevents duplicate runs/moves.
        """
        super().save_model(request, obj, form, change)


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
        "created_at",
        "run",
        "media_item",
        "old_physical_bin_label",
        "new_physical_bin_label",
        "is_done",
    )
    list_filter = ("is_done", "created_at", "run__zone", "run__bucket")
    search_fields = (
        "media_item__title",
        "media_item__artist__artist_name_primary",
        "old_physical_bin_label",
        "new_physical_bin_label",
    )
    actions = ["mark_done"]

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

    def move_count(self, obj):
        return obj.moves.count()

    def open_count(self, obj):
        return obj.moves.filter(is_done=False).count()
