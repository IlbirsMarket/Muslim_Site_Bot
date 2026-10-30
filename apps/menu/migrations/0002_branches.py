"""Меню филиала: у категорий и добавок появляется филиал (всё нынешнее — «Филиал 1»)."""

import django.db.models.deletion
from django.db import migrations, models

import apps.cafe.models


def to_first_branch(apps, schema_editor):
    """Всё, что было до филиалов, — первому филиалу."""
    first = apps.get_model("cafe", "Branch").objects.order_by("position", "id").first()
    apps.get_model("menu", "Category").objects.update(branch=first)
    apps.get_model("menu", "Extra").objects.update(branch=first)

class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0001_initial"),
        ("cafe", "0002_branches"),
    ]

    operations = [
        migrations.AddField(
            model_name="category", name="branch",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="categories",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.AddField(
            model_name="extra", name="branch",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="extras",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.RunPython(to_first_branch, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="category", name="branch",
            field=models.ForeignKey(
                default=apps.cafe.models.default_branch_id, on_delete=django.db.models.deletion.PROTECT, related_name="categories",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.AlterField(
            model_name="extra", name="branch",
            field=models.ForeignKey(
                default=apps.cafe.models.default_branch_id, on_delete=django.db.models.deletion.PROTECT, related_name="extras",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
    ]
