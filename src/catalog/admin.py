from django.contrib import admin, messages
from .models import StorageZone, MediaType, Artist, MediaItem, PhysicalBin, LogicalBin, BinMapping, SortBucket, BucketBinRange  # adjust imports to your file
from catalog.services.binning import assign_logical_bin 

@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "artist_type",
        "alpha_bucket",
        "sort_name",
        "updated_at",
    )
    list_filter = ("artist_type", "alpha_bucket")
    search_fields = ("artist_name_primary", "artist_name_secondary", "display_name", "sort_name")
    ordering = ("sort_name",)

    # ✅ Lock derived fields in admin (always read-only)
    readonly_fields = ("display_name", "sort_name", "alpha_bucket", "created_at", "updated_at")

    fieldsets = (
        ("Artist (data entry)", {
            "fields": ("artist_type", "artist_name_primary", "artist_name_secondary"),
        }),
        ("Computed (read-only)", {
            "fields": ("display_name", "sort_name", "alpha_bucket"),
        }),
        ("System", {
            "fields": ("created_at", "updated_at"),
        }),
    )
    
@admin.register(StorageZone)
class StorageZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_binned")
    search_fields = ("name", "code")


@admin.register(MediaType)
class MediaTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "default_zone", "is_vinyl", "requires_speed")
    list_filter = ("default_zone", "is_vinyl", "requires_speed")
    search_fields = ("name",)


# (Register Artist/MediaItem if not already)

@admin.register(PhysicalBin)
class PhysicalBinAdmin(admin.ModelAdmin):
    list_display = (
        "zone",
        "shelf_number",
        "bin_number",
        "is_active",
    )
    list_filter = ("zone", "is_active")
    ordering = ("zone__code", "shelf_number", "bin_number")
    search_fields = ("zone__code",)


@admin.register(LogicalBin)
class LogicalBinAdmin(admin.ModelAdmin):
    list_display = (
        "zone",
        "number",
        "capacity_override",
        "is_active",
    )
    list_filter = ("zone", "is_active")
    ordering = ("zone__code", "number")
    search_fields = ("zone__code",)


@admin.register(BinMapping)
class BinMappingAdmin(admin.ModelAdmin):
    list_display = (
        "logical_bin",
        "physical_bin",
        "is_active",
    )
    list_filter = ("is_active", "logical_bin__zone")
    search_fields = (
        "logical_bin__zone__code",
        "logical_bin__number",
        "physical_bin__zone__code",
    )

@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = ("artist", "title", "media_type", "Owner", "bucket", "effective_zone_display", "placement_status", "logical bin", "physical_bin_display")
    list_filter = ("media_type", "bucket", "Owner",  "media_type__default_zone")
    search_fields = ("title", "artist__artist_name_primary", "artist__artist_name_secondary")
    autocomplete_fields = ("artist", "media_type", "zone_override")

    def effective_zone_display(self, obj):
        return obj.effective_zone.name
    effective_zone_display.short_description = "Zone"

    def physical_bin_display(self, obj):
        pb = obj.physical_bin
        return str(pb) if pb else ""
    physical_bin_display.short_description = "Physical bin"

    list_display = ("artist", "title", "media_type", "bucket", "effective_zone_display", "logical_bin", "physical_bin_display")
    list_filter = ("bucket", "media_type", "media_type__default_zone")
    autocomplete_fields = ("artist", "media_type", "zone_override", "logical_bin", "bucket")
 
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

 # ✅ Lockdown: make logical_bin read-only for non-superusers
    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
         # Always read-only (derived / computed)
        ro.extend(["placement_status", "physical_bin_display"])

        # Placement should not be manually edited (engine owns it)
        ro.append("logical_bin")
        
        return ro

    @admin.action(description="Reassign bins (deterministic)")
    def reassign_bins(self, request, queryset):
        changed = 0
        for item in queryset.select_related("artist", "media_type", "zone_override", "bucket"):
            before = item.logical_bin_id
            result = assign_logical_bin(item, persist=True)
            after = item.logical_bin_id
            if after and after != before:
                changed += 1

        self.message_user(
            request,
            f"Reassign complete. Updated {changed} item(s).",
            level=messages.SUCCESS,
        )
    fieldsets = (
        ("Core info", {
            "fields": ("artist", "title", "owner", "pressing_year"),
            }),
        ("Classification inputs", {
            "fields": ("media_type", "bucket", "zone_override"),
            }),
        ("Placement (read-only)", {
            "fields": ("placement_status", "logical_bin", "physical_bin_display"),
            }),
            )

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