# Два этажа: у стола появляется этаж, номера считаются отдельно на каждом этаже.
# Старые столы становятся столами 1 этажа: «Стол 3» → «Стол 3 · 1 этаж».

import re

from django.db import migrations, models

OLD_AUTO_NAME = re.compile(r"^Стол( \d+)?$")       # прежнее автоматическое название


def add_floor_to_names(apps, schema_editor):
    """Автоматические названия «Стол N» дополняем этажом. Своё название (например, «У окна») не трогаем."""
    Table = apps.get_model("tables", "Table")
    for table in Table.objects.filter(kind="hall"):
        if not table.name or OLD_AUTO_NAME.match(table.name):
            table.name = f"Стол {table.number} · {table.floor} этаж"
            table.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0003_table_freed_at"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="table", name="unique_table_number_per_kind"),   # старое правило «номер на весь зал»
        migrations.AddField(
            model_name="table",
            name="floor",
            field=models.PositiveSmallIntegerField(choices=[(1, "1 этаж"), (2, "2 этаж")], default=1, verbose_name="Этаж"),
        ),
        migrations.AlterModelOptions(
            name="table",
            options={"ordering": ["kind", "floor", "number"], "verbose_name": "Стол", "verbose_name_plural": "Столы"},
        ),
        migrations.AddConstraint(                                                                 # новое: номер на своём этаже
            model_name="table",
            constraint=models.UniqueConstraint(fields=("kind", "floor", "number"), name="unique_table_number_per_floor"),
        ),
        migrations.RunPython(add_floor_to_names, migrations.RunPython.noop),
    ]
