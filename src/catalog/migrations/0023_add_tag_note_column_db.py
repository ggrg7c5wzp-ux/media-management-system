from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0022_fix_tag_sort_order_column"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE catalog_tag
                ADD COLUMN IF NOT EXISTS tag_note text NOT NULL DEFAULT '';
            """,
            reverse_sql="""
                ALTER TABLE catalog_tag
                DROP COLUMN IF EXISTS tag_note;
            """,
        ),
    ]
