from django.db import models
from django.core.validators import MinValueValidator

class ArtistType(models.TextChoices):
    PERSON = "PERSON", "Person"
    BAND = "BAND", "Band"


def _normalize_sort_name(name: str) -> str:
    """
    Sorting rules:
      - Strip leading 'The' only
      - Normalize whitespace
    """
    if not name:
        return ""

    n = " ".join(name.strip().split())

    lower = n.lower()
    if lower.startswith("the "):
        n = n[4:]

    return n.strip()

def _normalize_person_name(name: str) -> str:
    """
    Normalize human names to Title Case, trimming whitespace.
    Example: 'eric' -> 'Eric', 'van halen' -> 'Van Halen'
    """
    if not name:
        return ""
    return " ".join(part.capitalize() for part in name.strip().split())

class Artist(models.Model):
    artist_name_primary = models.CharField(max_length=200)
    artist_name_secondary = models.CharField(max_length=200, blank=True, default="")
    artist_type = models.CharField(
        max_length=10,
        choices=ArtistType.choices,
        default=ArtistType.BAND,
    )

    # Stored derived fields (fast sorting + filtering)
    display_name = models.CharField(max_length=220, editable=False)
    sort_name = models.CharField(max_length=220, db_index=True, editable=False)
    alpha_bucket = models.CharField(max_length=1, db_index=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def _compute_display_name(self) -> str:
        # BAND: primary holds the full band name
        # PERSON: primary = first name(s), secondary = last name
        if self.artist_type == ArtistType.PERSON:
            first = self.artist_name_primary.strip()
            last = self.artist_name_secondary.strip()
            return f"{first} {last}".strip()

        return self.artist_name_primary.strip()

    def save(self, *args, **kwargs):
          # --- Validation ---
        if self.artist_type == ArtistType.BAND:
            if not self.artist_name_primary or not self.artist_name_primary.strip():
                raise ValueError("Band artists require a primary name")

        if self.artist_type == ArtistType.PERSON:
            if not self.artist_name_primary or not self.artist_name_primary.strip():
                raise ValueError("Person artists require a first name")
            if not self.artist_name_secondary or not self.artist_name_secondary.strip():
                raise ValueError("Person artists require a last name")
            
         # --- Normalization---  
        if self.artist_type == ArtistType.PERSON:
            first = _normalize_person_name(self.artist_name_primary)
            last = _normalize_person_name(self.artist_name_secondary)

            self.artist_name_primary = first
            self.artist_name_secondary = last

            self.display_name = f"{first} {last}".strip()
            base_sort = f"{last}, {first}".strip()
        else:
            # BAND: preserve user-entered casing
            self.artist_name_primary = self.artist_name_primary.strip()
            self.artist_name_secondary = self.artist_name_secondary.strip()

            self.display_name = self.artist_name_primary
            base_sort = self.display_name

    # Normalize sort name (The-handling etc.)
        self.sort_name = _normalize_sort_name(base_sort)

    # Alpha bucket
        first_char = self.sort_name[:1].upper() if self.sort_name else "#"
        self.alpha_bucket = first_char if first_char.isalpha() else "#"

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.display_name
    class Meta:
        verbose_name = "Artist"
        verbose_name_plural = "Artists"

class StorageZone(models.Model):
    """
    A storage 'area' that has its own bin universe (e.g., Garage Main vs Office Shelf).
    """
    code = models.CharField(max_length=50, unique=True)   # e.g., GARAGE_MAIN
    name = models.CharField(max_length=100)               # e.g., Garage Main
    description = models.CharField(max_length=255, blank=True, default="")
    is_binned = models.BooleanField(default=True)         # future-proof: a zone could be non-binned

    def __str__(self) -> str:
        return self.name


class MediaType(models.Model):
    """
    Replaces/modernizes tblMediaType. MediaType defines handling + default storage zone.
    """
    name = models.CharField(max_length=100, unique=True)  # e.g., Standard LP, Box Set
    default_zone = models.ForeignKey(
        StorageZone,
        on_delete=models.PROTECT,
        related_name="media_types",
    )
    is_vinyl = models.BooleanField(default=False)
    requires_speed = models.BooleanField(default=False)   # ties into your '33 1/3 vs 45' rule

    def __str__(self) -> str:
        return self.name

class MediaItem(models.Model):
    artist = models.ForeignKey("Artist", on_delete=models.PROTECT, related_name="media_items")
    title = models.CharField(max_length=255)
    pressing_year = models.PositiveIntegerField(null=True, blank=True)

    media_type = models.ForeignKey("MediaType", on_delete=models.PROTECT, related_name="media_items")

    zone_override = models.ForeignKey(
        "StorageZone",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="override_items",
    )

    # ✅ NEW: for now, manual assignment; later the engine will set/maintain this deterministically
    logical_bin = models.ForeignKey(
        "LogicalBin",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="media_items",
    )

    @property
    def effective_zone(self) -> "StorageZone":
        return self.zone_override or self.media_type.default_zone

    @property
    def physical_bin(self):
        """
        Resolve physical bin via logical_bin -> mapping -> physical_bin.
        Returns None if not assigned or not mapped.
        """
        if not self.logical_bin:
            return None
        mapping = getattr(self.logical_bin, "mapping", None)
        return mapping.physical_bin if mapping and mapping.is_active else None

    def __str__(self) -> str:
        return f"{self.artist} — {self.title}"
    
    bucket = models.ForeignKey(
    "SortBucket",
    null=True,
    blank=True,
    on_delete=models.PROTECT,
    related_name="media_items",
)

class PhysicalBin(models.Model):
    """
    A real-world bin/location inside a StorageZone.
    Example: GARAGE_MAIN Shelf 1 Bin 1
    """
    zone = models.ForeignKey("StorageZone", on_delete=models.PROTECT, related_name="physical_bins")

    shelf_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    bin_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    # Optional: human-facing label, computed later if you want
    label = models.CharField(max_length=50, blank=True, default="")

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "shelf_number", "bin_number"],
                name="uniq_physicalbin_zone_shelf_bin",
            )
        ]
        ordering = ["zone__code", "shelf_number", "bin_number"]

    def __str__(self) -> str:
        return f"{self.zone.code}: Shelf {self.shelf_number} Bin {self.bin_number}"


class LogicalBin(models.Model):
    """
    A logical bin number inside a zone (the bin universe for placement).
    Example: GARAGE_MAIN #1..#48
    """
    zone = models.ForeignKey("StorageZone", on_delete=models.PROTECT, related_name="logical_bins")
    number = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    # Capacity hooks (we’ll use this soon)
    capacity_override = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "number"],
                name="uniq_logicalbin_zone_number",
            )
        ]
        ordering = ["zone__code", "number"]

    def __str__(self) -> str:
        return f"{self.zone.code} #{self.number}"


class BinMapping(models.Model):
    """
    Maps a logical bin to a physical bin (human-controlled).
    Usually 1:1, but we allow changes later.
    """
    logical_bin = models.OneToOneField("LogicalBin", on_delete=models.CASCADE, related_name="mapping")
    physical_bin = models.ForeignKey("PhysicalBin", on_delete=models.PROTECT, related_name="mappings")

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # Only one ACTIVE mapping per physical bin (prevents collisions)
            models.UniqueConstraint(
                fields=["physical_bin"],
                condition=models.Q(is_active=True),
                name="uniq_active_mapping_per_physicalbin",
            )
        ]

    def __str__(self) -> str:
        return f"{self.logical_bin} -> {self.physical_bin}"
    
class SortBucket(models.Model):
    """
    A high-level grouping that drives binning (e.g., Country, Rock, New Wave).
    This is NOT a tag. This is the primary filing/bucket dimension.
    """
    code = models.CharField(max_length=50, unique=True)  # e.g., COUNTRY, ROCK
    name = models.CharField(max_length=100)              # e.g., Country
    sort_order = models.PositiveIntegerField(default=100)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name
    
class BucketBinRange(models.Model):
    """
    Defines which logical bin numbers a SortBucket is allowed to occupy within a StorageZone.
    Example: GARAGE_MAIN + COUNTRY = bins 1..7
    """
    zone = models.ForeignKey("StorageZone", on_delete=models.PROTECT, related_name="bucket_ranges")
    bucket = models.ForeignKey("SortBucket", on_delete=models.PROTECT, related_name="bin_ranges")

    start_bin = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    end_bin = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "bucket"],
                name="uniq_bucket_range_per_zone_bucket",
            ),
          models.CheckConstraint(
                condition=models.Q(end_bin__gte=models.F("start_bin")),
                name="chk_bucket_range_end_gte_start",
)

        ]
        ordering = ["zone__code", "start_bin", "end_bin"]

    def __str__(self) -> str:
        return f"{self.zone.code} | {self.bucket.name}: {self.start_bin}-{self.end_bin}"