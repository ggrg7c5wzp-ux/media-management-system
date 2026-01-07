import pytest
from catalog.models import Artist, ArtistType


@pytest.mark.django_db
def test_band_keeps_name_and_strips_the_for_sort():
    a = Artist.objects.create(
        artist_name_primary="The Cure",
        artist_type=ArtistType.BAND,
    )
    assert a.display_name == "The Cure"
    assert a.sort_name == "Cure"
    assert a.alpha_bucket == "C"


@pytest.mark.django_db
def test_person_sorts_last_comma_first_and_alpha_bucket_is_last_initial():
    a = Artist.objects.create(
        artist_name_primary="Eric",
        artist_name_secondary="Church",
        artist_type=ArtistType.PERSON,
    )
    assert a.display_name == "Eric Church"
    assert a.sort_name == "Church, Eric"
    assert a.alpha_bucket == "C"


@pytest.mark.django_db
def test_band_requires_primary_name():
    with pytest.raises(ValueError):
        Artist.objects.create(
            artist_name_primary="",
            artist_type=ArtistType.BAND,
        )


@pytest.mark.django_db
def test_person_requires_first_and_last():
    with pytest.raises(ValueError):
        Artist.objects.create(
            artist_name_primary="Eric",
            artist_name_secondary="",
            artist_type=ArtistType.PERSON,
        )
