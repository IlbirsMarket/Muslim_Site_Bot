"""Столы филиала: номера столов свои в каждом филиале и на каждом этаже."""

import django.db.models.deletion
from django.db import migrations, models

import apps.cafe.models


def to_first_branch(apps, schema_editor):
    """Всё, что было до филиалов, — первому филиалу."""
    first = apps.get_model("cafe", "Branch").objects.order_by("position", "id").first()
    apps.get_model("tables", "Table").objects.update(branch=first)

class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0004_table_floors"),
        ("cafe", "0002_branches"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="table", name="unique_table_number_per_floor"),
        migrations.AddField(
            model_name="table", name="branch",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="tables",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.RunPython(to_first_branch, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="table", name="branch",
            field=models.ForeignKey(
                default=apps.cafe.models.default_branch_id, on_delete=django.db.models.deletion.PROTECT, related_name="tables",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.AddConstraint(
            model_name="table",
            constraint=models.UniqueConstraint(
                fields=("branch", "kind", "floor", "number"), name="unique_table_number_per_branch_floor",
            ),
        ),
    ]
