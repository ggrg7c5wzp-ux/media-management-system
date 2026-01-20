from django.db import migrations


class Migration(migrations.Migration):
    """
    RECONSTRUCTED MIGRATION FILE.

    The database already contains the tables/constraints created by this migration
    (Tag, ArtistTag, MediaItemTag, and M2M fields) and Django's django_migrations
    already marks this migration as applied.

    This file exists to restore missing migration history in the repo so Django
    can build correct state and avoid generating conflicting migration numbers.
    """

    dependencies = [
        ("catalog", "0015_alter_mediaitem_options"),
    ]

    operations = []
