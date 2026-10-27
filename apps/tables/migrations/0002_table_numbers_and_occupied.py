# Новые правила столов: номера ставятся сами, доставка ровно одна, у стола появилось «Занят с».

from django.db import migrations, models


def number_existing(apps, schema_editor):
    """
    Старые данные под новые правила:
    - у столов без номера появляются номера, названия «Стол N»;
    - доставка ровно одна: номер 1, название «Доставка» (лишние доставки отключаем, нет ни одной — создаём).
    """
    Table = apps.get_model("tables", "Table")

    used = set(Table.objects.filter(kind="hall").exclude(number=None).values_list("number", flat=True))
    next_number = 1
    for table in Table.objects.filter(kind="hall", number=None).order_by("id"):
        while next_number in used:                           # пропускаем занятые номера
            next_number += 1
        table.number = next_number
        used.add(next_number)
        if not table.name:
            table.name = f"Стол {next_number}"
        table.save(update_fields=["number", "name"])

    deliveries = list(Table.objects.filter(kind="delivery").order_by("id"))
    if not deliveries:                                       # доставки нет — создаём
        Table.objects.create(kind="delivery", number=1, name="Доставка")
    else:
        main, extra = deliveries[0], deliveries[1:]
        for i, other in enumerate(extra, start=2):           # лишние доставки: отключаем, номер не мешает
            other.number = 1000 + i
            other.is_active = False
            other.save(update_fields=["number", "is_active"])
        main.number = 1
        main.name = "Доставка"
        main.is_active = True
        main.save(update_fields=["number", "name", "is_active"])


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="table",
            name="number",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="Номер"),
        ),
        migrations.AddField(
            model_name="table",
            name="occupied_since",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Занят с"),
        ),
        migrations.RunPython(number_existing, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="table",
            constraint=models.UniqueConstraint(fields=("kind", "number"), name="unique_table_number_per_kind"),
        ),
    ]