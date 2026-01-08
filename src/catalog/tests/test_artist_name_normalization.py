import pytest
from catalog.models import Artist, ArtistType

pytestmark = pytest.mark.django_db


def test_person_name_is_capitalized():
    a = Artist.objects.create(
        artist_type=ArtistType.PERSON,
        artist_name_primary="eric",
        artist_name_secondary="church",
    )
    a.refresh_from_db()
    assert a.artist_name_primary == "Eric"
    assert a.artist_name_secondary == "Church"


def test_band_name_is_preserved():
    a = Artist.objects.create(
        artist_type=ArtistType.BAND,
        artist_name_primary="k.d. lang",
        artist_name_secondary="",
    )
    a.refresh_from_db()
    assert a.artist_name_primary == "k.d. lang"
