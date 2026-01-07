from django.contrib import admin
from .models import Artist


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ("display_name", "artist_type", "alpha_bucket", "sort_name", "updated_at")
    list_filter = ("artist_type", "alpha_bucket")
    search_fields = ("artist_name_primary", "artist_name_secondary", "display_name", "sort_name")
    ordering = ("sort_name",)
