"""Заказ знает свой филиал (берётся со стола)."""

import django.db.models.deletion
from django.db import migrations, models

import apps.cafe.models


def to_first_branch(apps, schema_editor):
    """Всё, что было до филиалов, — первому филиалу."""
    first = apps.get_model("cafe", "Branch").objects.order_by("position", "id").first()
    Order = apps.get_model("orders", "Order")
    for order in Order.objects.select_related("table").iterator():
        branch_id = order.table.branch_id if order.table_id else first.id   # филиал стола, иначе первый
        Order.objects.filter(pk=order.pk).update(branch_id=branch_id)

class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0002_alter_order_kind"),
        ("cafe", "0002_branches"),
        ("tables", "0005_branches"),
    ]

    operations = [
        migrations.AddField(
            model_name="order", name="branch",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="orders",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.RunPython(to_first_branch, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="order", name="branch",
            field=models.ForeignKey(
                default=apps.cafe.models.default_branch_id, on_delete=django.db.models.deletion.PROTECT, related_name="orders",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
    ]
