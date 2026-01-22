from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0020_create_missing_tag_tables"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE catalog_storagezone
                ADD COLUMN IF NOT EXISTS bins_per_shelf integer NOT NULL DEFAULT 8;
            """,
            reverse_sql="""
                ALTER TABLE catalog_storagezone
                DROP COLUMN IF EXISTS bins_per_shelf;
            """,
        ),
    ]
