from django.db import models


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
        # Validate required fields based on artist type
        if self.artist_type == ArtistType.PERSON:
            if not (self.artist_name_primary and self.artist_name_primary.strip()):
                raise ValueError("Person artists require a first name.")
            if not (self.artist_name_secondary and self.artist_name_secondary.strip()):
                raise ValueError("Person artists require a last name.")
        else:
            if not (self.artist_name_primary and self.artist_name_primary.strip()):
                raise ValueError("Band artists require a name.")

        # Compute display name
        self.display_name = self._compute_display_name()

        # Compute sort base
        base_sort = self.display_name

        # PERSON: sort by last name, then first name(s)
        if self.artist_type == ArtistType.PERSON:
            first = self.artist_name_primary.strip()
            last = self.artist_name_secondary.strip()
            base_sort = f"{last}, {first}".strip()

        # Normalize sort name
        self.sort_name = _normalize_sort_name(base_sort)

        # Alpha bucket
        first_char = self.sort_name[:1].upper() if self.sort_name else "#"
        self.alpha_bucket = first_char if first_char.isalpha() else "#"

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.display_name
