from django.db import migrations


class Migration(migrations.Migration):
    """
    RECONSTRUCTED MIGRATION FILE.

    bins_per_shelf exists in DB already; repo was missing file. Restores migration graph only.
    """

    dependencies = [
        ("catalog", "0017_alter_tag_slug_tag_uniq_tag_scope_slug_and_more"),
    ]

    operations = []
