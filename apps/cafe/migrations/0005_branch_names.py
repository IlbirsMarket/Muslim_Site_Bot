"""Названия филиалов по месту: «Филиал 1» → «Кара-Суу», «Филиал 2» → «Таширов» (если шеф их ещё не переименовал)."""

from django.db import migrations

NAMES = {"Филиал 1": "Кара-Суу", "Филиал 2": "Таширов"}


def rename(apps, schema_editor):
    Branch = apps.get_model("cafe", "Branch")
    for old, new in NAMES.items():
        Branch.objects.filter(name=old).update(name=new)


def back(apps, schema_editor):
    Branch = apps.get_model("cafe", "Branch")
    for old, new in NAMES.items():
        Branch.objects.filter(name=new).update(name=old)


class Migration(migrations.Migration):

    dependencies = [("cafe", "0004_branch_tg_start_token")]

    operations = [migrations.RunPython(rename, back)]
