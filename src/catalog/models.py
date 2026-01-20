from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify

# -----------------------------------------------------------------------------
# Artist
# -----------------------------------------------------------------------------


class ArtistType(models.TextChoices):
    PERSON = "PERSON", "Person"
    BAND = "BAND", "Band"


def _normalize_sort_name(name: str) -> str:
    """Normalize a name for sorting.

    Rules:
      - Strip leading 'The' only
      - Normalize whitespace
    """
    if not name:
        return ""

    n = " ".join(name.strip().split())
    if n.lower().startswith("the "):
        n = n[4:]
    return n.strip()


def _normalize_person_name(name: str) -> str:
    """Normalize human names to Title Case, trimming whitespace."""
    if not name:
        return ""
    return " ".join(part.capitalize() for part in name.strip().split())


class Artist(models.Model):
    # Data entry fields
    artist_name_primary = models.CharField(max_length=200)
    artist_name_secondary = models.CharField(max_length=200, blank=True, default="")

    name_suffix = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Suffix like Jr, Sr, II, III (PERSON artists only)",
    )

    filed_under_artist = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="files_here",
        help_text="Optional artist to file this artist under for sorting/binning",
    )

    artist_type = models.CharField(
        max_length=10,
        choices=ArtistType.choices,
        default=ArtistType.BAND,
    )

    # Stored derived fields (fast sorting + filtering)
    display_name = models.CharField(max_length=220, editable=False)
    sort_name = models.CharField(max_length=220, db_index=True, editable=False)
    alpha_bucket = models.CharField(max_length=1, db_index=True, editable=False)

    # Tagging (artist-scoped)
    tags = models.ManyToManyField("Tag", through="ArtistTag", blank=True, related_name="artists")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ---- Computed filing properties ----
    @property
    def filing_artist(self) -> "Artist":
        """The artist we file under for sorting/binning."""
        return self.filed_under_artist if self.filed_under_artist is not None else self

    @property
    def filing_sort_name(self) -> str:
        return self.filing_artist.sort_name

    @property
    def filing_alpha_bucket(self) -> str:
        return self.filing_artist.alpha_bucket

    def clean(self):
        super().clean()
        # Prevent filing-under-self (works for existing + newly-created with pk set)
        if self.filed_under_artist and self.pk and self.filed_under_artist.pk == self.pk:
            raise ValidationError({"filed_under_artist": "An artist cannot be filed under itself."})

    def save(self, *args, **kwargs):
        # --- Validation ---
        if self.artist_type == ArtistType.BAND:
            if not (self.artist_name_primary or "").strip():
                raise ValueError("Band artists require a primary name")

        if self.artist_type == ArtistType.PERSON:
            if not (self.artist_name_primary or "").strip():
                raise ValueError("Person artists require a first name")
            if not (self.artist_name_secondary or "").strip():
                raise ValueError("Person artists require a last name")

        # --- Normalization + Derived fields (base) ---
        if self.artist_type == ArtistType.PERSON:
            first = _normalize_person_name(self.artist_name_primary)
            last = _normalize_person_name(self.artist_name_secondary)

            suffix = (self.name_suffix or "").strip()
            suffix_map = {
                "JR": "Jr",
                "JR.": "Jr",
                "SR": "Sr",
                "SR.": "Sr",
                "II": "II",
                "III": "III",
                "IV": "IV",
                "V": "V",
            }
            suffix_norm = suffix_map.get(suffix.upper(), suffix)
            self.name_suffix = suffix_norm

            suffix_part = f" {suffix_norm}" if suffix_norm else ""

            self.artist_name_primary = first
            self.artist_name_secondary = last

            self.display_name = f"{first} {last}{suffix_part}"
            self.sort_name = f"{last}, {first}{suffix_part}"

        else:  # BAND
            name = " ".join((self.artist_name_primary or "").strip().split())
            self.artist_name_primary = name
            self.artist_name_secondary = ""  # band has no secondary
            self.name_suffix = ""  # suffix only meaningful for PERSON

            self.display_name = name
            self.sort_name = _normalize_sort_name(name)

        # --- Alpha bucket (base) ---
        first_char = self.sort_name[:1].upper() if self.sort_name else "#"
        self.alpha_bucket = first_char if first_char.isalpha() else "#"

        # --- FILE UNDER override (stored fields) ---
        filing = self.filed_under_artist
        if filing is not None:
            # Ensure we have the fields (in case of deferred load)
            if not getattr(filing, "sort_name", None) or not getattr(filing, "alpha_bucket", None):
                filing = Artist.objects.only("sort_name", "alpha_bucket").get(pk=filing.pk)
            self.sort_name = filing.sort_name
            self.alpha_bucket = filing.alpha_bucket

        super().save(*args, **kwargs)

        # Keep dependents in sync when this artist changes.
        Artist.objects.filter(filed_under_artist=self).exclude(pk=self.pk).update(
            sort_name=self.sort_name,
            alpha_bucket=self.alpha_bucket,
        )

    def __str__(self) -> str:
        return self.display_name

    class Meta:
        verbose_name = "Artist"
        verbose_name_plural = "Artists"
        ordering = ["sort_name"]


# -----------------------------------------------------------------------------
# Tagging
# -----------------------------------------------------------------------------


class Tag(models.Model):
    class Scope(models.TextChoices):
        ARTIST = "ARTIST", "Artist"
        MEDIA_ITEM = "MEDIA_ITEM", "Media Item"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    scope = models.CharField(max_length=20, choices=Scope.choices)
    sort_order = models.PositiveIntegerField(default=0)
    tag_note = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.scope})"

    class Meta:
        ordering = ("scope", "sort_order", "name")
        constraints = [
            models.UniqueConstraint(fields=["scope", "slug"], name="uniq_tag_scope_slug"),
            models.UniqueConstraint(fields=["scope", "name"], name="uniq_tag_scope_name"),
        ]


class ArtistTag(models.Model):
    artist = models.ForeignKey("Artist", on_delete=models.CASCADE, related_name="artist_tags")
    tag = models.ForeignKey("Tag", on_delete=models.CASCADE, related_name="artist_tags")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["artist", "tag"], name="uniq_artist_tag"),
        ]

    def clean(self):
        super().clean()
        if self.tag and self.tag.scope != Tag.Scope.ARTIST:
            raise ValidationError({"tag": "This tag is not ARTIST-scoped."})

    def __str__(self) -> str:
        return f"{self.artist} ↔ {self.tag}"


class MediaItemTag(models.Model):
    media_item = models.ForeignKey("MediaItem", on_delete=models.CASCADE, related_name="media_item_tags")
    tag = models.ForeignKey("Tag", on_delete=models.CASCADE, related_name="media_item_tags")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["media_item", "tag"], name="uniq_media_item_tag"),
        ]

    def clean(self):
        super().clean()
        if self.tag and self.tag.scope != Tag.Scope.MEDIA_ITEM:
            raise ValidationError({"tag": "This tag is not MEDIA_ITEM-scoped."})

    def __str__(self) -> str:
        return f"{self.media_item} ↔ {self.tag}"


# -----------------------------------------------------------------------------
# Storage / Media
# -----------------------------------------------------------------------------


class StorageZone(models.Model):
    """A storage 'area' that has its own bin universe (e.g., Garage Main vs Office Shelf)."""

    class SortStrategy(models.TextChoices):
        BUCKETED = "BUCKETED", "Bucketed (uses bucket bin ranges)"
        ALPHA_ONLY = "ALPHA_ONLY", "Alpha-only (ignores buckets)"

    code = models.CharField(max_length=50, unique=True)  # e.g., GARAGE_MAIN
    name = models.CharField(max_length=100)  # e.g., Garage Main
    description = models.CharField(max_length=255, blank=True, default="")
    is_binned = models.BooleanField(default=True)

    sort_strategy = models.CharField(
        max_length=16,
        choices=SortStrategy.choices,
        default=SortStrategy.BUCKETED,
    )

    default_bin_capacity = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1)],
        help_text="Default max items per logical bin in this zone (used unless a bin has capacity_override).",
    )

    bins_per_shelf = models.PositiveIntegerField(
        default=8,
        validators=[MinValueValidator(1)],
        help_text="How many physical bins exist per shelf in this zone (used to compute linear bin numbers).",
    )

    def __str__(self) -> str:
        return self.name

    class Meta:
        ordering = ["code"]


class MediaType(models.Model):
    """Defines handling + default storage zone."""

    name = models.CharField(max_length=100, unique=True)  # e.g., Standard LP, Box Set
    default_zone = models.ForeignKey(StorageZone, on_delete=models.PROTECT, related_name="media_types")

    is_vinyl = models.BooleanField(default=False)
    requires_speed = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name

    class Meta:
        ordering = ["name"]


class CollectionOwner(models.TextChoices):
    ME = "ME", "Mine"
    BIL = "BIL", "Brother-in-law"


class SortBucket(models.Model):
    """Primary filing/bucket dimension (genre-ish)."""

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class LogicalBin(models.Model):
    """A logical bin number inside a zone."""

    zone = models.ForeignKey(StorageZone, on_delete=models.PROTECT, related_name="logical_bins")
    number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    capacity_override = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["zone", "number"], name="uniq_logicalbin_zone_number"),
        ]
        ordering = ["zone__code", "number"]

    def __str__(self) -> str:
        return f"{self.zone.code} #{self.number}"

    @property
    def effective_capacity(self) -> int:
        return int(self.capacity_override) if self.capacity_override is not None else int(self.zone.default_bin_capacity)


class PhysicalBin(models.Model):
    """A real-world bin/location inside a StorageZone."""

    zone = models.ForeignKey(StorageZone, on_delete=models.PROTECT, related_name="physical_bins")
    shelf_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    bin_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    label = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "shelf_number", "bin_number"],
                name="uniq_physicalbin_zone_shelf_bin",
            ),
        ]
        ordering = ["zone__code", "shelf_number", "bin_number"]

    def __str__(self) -> str:
        return f"{self.zone.code}: Shelf {self.shelf_number} Bin {self.bin_number}"

    @property
    def active_mapping(self):
        """Return the active BinMapping for this PhysicalBin, if any."""
        mgr = getattr(self, "mappings", None) or getattr(self, "binmapping_set", None)
        if mgr is None:
            return None
        return mgr.filter(is_active=True).select_related("logical_bin", "logical_bin__zone").first()

    @property
    def effective_capacity(self) -> int:
        """Effective capacity of the physical bin."""
        mapping = self.active_mapping
        if mapping and mapping.logical_bin_id:
            return mapping.logical_bin.effective_capacity
        return int(self.zone.default_bin_capacity)

    @property
    def linear_bin_number(self) -> int:
        """A 1..N 'label bin number' within a zone."""
        bps = int(getattr(self.zone, "bins_per_shelf", 8) or 8)
        return (int(self.shelf_number) - 1) * bps + int(self.bin_number)


class BinMapping(models.Model):
    """Maps a logical bin to a physical bin (human-controlled)."""

    logical_bin = models.OneToOneField(LogicalBin, on_delete=models.CASCADE, related_name="mapping")
    physical_bin = models.ForeignKey(PhysicalBin, on_delete=models.PROTECT, related_name="mappings")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["physical_bin"],
                condition=models.Q(is_active=True),
                name="uniq_active_mapping_per_physicalbin",
            )
        ]

    def __str__(self) -> str:
        return f"{self.logical_bin} -> {self.physical_bin}"


class MediaItem(models.Model):
    master_key = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="Stable ID from the legacy catalog (e.g., A1234). Used for idempotent imports.",
    )

    artist = models.ForeignKey(Artist, on_delete=models.PROTECT, related_name="media_items")
    title = models.CharField(max_length=255)

    pressing_year = models.PositiveIntegerField(null=True, blank=True)
    release_year = models.PositiveIntegerField(null=True, blank=True)

    media_type = models.ForeignKey(MediaType, on_delete=models.PROTECT, related_name="media_items")

    owner = models.CharField(
        max_length=10,
        choices=CollectionOwner.choices,
        default=CollectionOwner.ME,
    )

    bucket = models.ForeignKey(
        SortBucket,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="media_items",
    )

    zone_override = models.ForeignKey(
        StorageZone,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="override_items",
    )

    logical_bin = models.ForeignKey(
        LogicalBin,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="media_items",
    )

    # Tagging (media-item-scoped)
    tags = models.ManyToManyField("Tag", through="MediaItemTag", blank=True, related_name="media_items")

    @property
    def effective_zone(self) -> StorageZone:
        return self.zone_override or self.media_type.default_zone

    @property
    def physical_bin(self):
        """Resolve physical bin via logical_bin -> mapping -> physical_bin."""
        if not self.logical_bin:
            return None
        mapping = getattr(self.logical_bin, "mapping", None)
        return mapping.physical_bin if mapping and mapping.is_active else None

    def __str__(self) -> str:
        return self.title

    class Meta:
        ordering = ["artist__sort_name", "title"]


class BucketBinRange(models.Model):
    """Defines which logical bin numbers a SortBucket is allowed to occupy within a StorageZone."""

    zone = models.ForeignKey(StorageZone, on_delete=models.PROTECT, related_name="bucket_ranges")
    bucket = models.ForeignKey(SortBucket, on_delete=models.PROTECT, related_name="bin_ranges")
    start_bin = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    end_bin = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.zone and getattr(self.zone, "sort_strategy", None) != StorageZone.SortStrategy.BUCKETED:
            raise ValidationError(
                {"zone": "Bucket bin ranges can only be defined for BUCKETED zones (e.g., Garage Main)."}
            )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["zone", "bucket"], name="uniq_bucket_range_per_zone_bucket"),
            models.CheckConstraint(
                condition=models.Q(end_bin__gte=models.F("start_bin")),
                name="chk_bucket_range_end_gte_start",
            ),
        ]
        ordering = ["zone__code", "start_bin", "end_bin"]

    def __str__(self) -> str:
        return f"{self.zone.code} | {self.bucket.name}: {self.start_bin}-{self.end_bin}"


# -----------------------------------------------------------------------------
# Rebin logging
# -----------------------------------------------------------------------------


class RebinRun(models.Model):
    """One 'Generate Task List' run. Groups the moves produced by a rebin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    zone = models.ForeignKey(StorageZone, on_delete=models.SET_NULL, null=True, blank=True)
    bucket = models.ForeignKey(SortBucket, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True, default="")

    def __str__(self) -> str:
        target = self.zone or self.bucket or "scope"
        return f"RebinRun {self.created_at:%Y-%m-%d %H:%M} ({target})"

    class Meta:
        ordering = ["-created_at"]


class RebinMove(models.Model):
    """A single physical move suggestion created by a rebin run."""

    run = models.ForeignKey(RebinRun, on_delete=models.CASCADE, related_name="moves")
    created_at = models.DateTimeField(auto_now_add=True)

    media_item = models.ForeignKey(MediaItem, on_delete=models.CASCADE, related_name="rebin_moves")

    old_logical_bin = models.ForeignKey(
        LogicalBin, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    new_logical_bin = models.ForeignKey(
        LogicalBin, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    old_physical_bin_label = models.CharField(max_length=128, blank=True, default="")
    new_physical_bin_label = models.CharField(max_length=128, blank=True, default="")

    is_done = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["is_done"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.media_item} :: {self.old_physical_bin_label} -> {self.new_physical_bin_label}"
