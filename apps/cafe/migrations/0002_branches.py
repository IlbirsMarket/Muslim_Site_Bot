"""
Филиалы. Всё, что было до них, становится «Филиалом 1». «Филиал 2» создаётся пустым:
его настройки копируются с первого (кроме адреса и телефона), меню и столы — свои.
"""

import django.db.models.deletion
from django.db import migrations, models

import apps.cafe.models


def create_branches(apps, schema_editor):
    """Создаём «Филиал 1» и «Филиал 2» (если их ещё нет)."""
    Branch = apps.get_model("cafe", "Branch")
    if not Branch.objects.exists():
        Branch.objects.create(name="Филиал 1", position=10)
        Branch.objects.create(name="Филиал 2", position=20)


def attach_settings(apps, schema_editor):
    """Нынешние настройки — первому филиалу; второму — копия без адреса и телефона."""
    Branch = apps.get_model("cafe", "Branch")
    CafeSettings = apps.get_model("cafe", "CafeSettings")
    first, *others = list(Branch.objects.order_by("position", "id"))
    current = CafeSettings.objects.order_by("id").first()
    if current is None:                                            # настроек ещё не было — создаём по умолчанию
        current = CafeSettings.objects.create(branch=first)
    else:
        CafeSettings.objects.filter(pk=current.pk).update(branch=first)
        CafeSettings.objects.exclude(pk=current.pk).delete()      # на всякий случай: лишних строк быть не должно
    copy = {
        f.name: getattr(current, f.name) for f in CafeSettings._meta.fields
        if f.name not in ("id", "branch", "address", "phone", "updated_at")
    }
    for branch in others:
        if not CafeSettings.objects.filter(branch=branch).exists():
            CafeSettings.objects.create(branch=branch, **copy)


class Migration(migrations.Migration):

    dependencies = [
        ("cafe", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Branch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, verbose_name="Название")),
                ("position", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
                ("is_active", models.BooleanField(default=True, verbose_name="Работает")),
            ],
            options={"verbose_name": "Филиал", "verbose_name_plural": "Филиалы", "ordering": ["position", "id"]},
        ),
        migrations.RunPython(create_branches, migrations.RunPython.noop),
        migrations.AddField(
            model_name="cafesettings",
            name="branch",
            field=models.OneToOneField(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="settings",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.RunPython(attach_settings, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="cafesettings",
            name="branch",
            field=models.OneToOneField(
                default=apps.cafe.models.default_branch_id, on_delete=django.db.models.deletion.CASCADE,
                related_name="settings", to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.AlterModelOptions(
            name="cafesettings",
            options={"verbose_name": "Настройки кафе", "verbose_name_plural": "Настройки кафе"},
        ),
    ]
