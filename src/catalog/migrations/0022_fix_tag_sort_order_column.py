from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0021_fix_tag_sort_order_column"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE IF EXISTS catalog_tag
            ADD COLUMN IF NOT EXISTS sort_order integer NOT NULL DEFAULT 0;
            """,
            reverse_sql="""
            ALTER TABLE IF EXISTS catalog_tag
            DROP COLUMN IF EXISTS sort_order;
            """,
        ),
    ]
