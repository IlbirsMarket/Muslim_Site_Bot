"""Сотрудник привязан к филиалу. Шеф и программист — без филиала (видят все)."""

import django.db.models.deletion
from django.db import migrations, models

import apps.cafe.models


def to_first_branch(apps, schema_editor):
    """Всё, что было до филиалов, — первому филиалу."""
    first = apps.get_model("cafe", "Branch").objects.order_by("position", "id").first()
    User = apps.get_model("users", "User")
    User.objects.exclude(role__in=["", "chef", "programmer"]).update(branch=first)

class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_alter_user_role_courier"),
        ("cafe", "0002_branches"),
    ]

    operations = [
        migrations.AddField(
            model_name="user", name="branch",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="staff",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.RunPython(to_first_branch, migrations.RunPython.noop),
    ]
