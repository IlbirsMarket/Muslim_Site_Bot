"""У филиала — своя Telegram-группа с темами. Группа из .env (TELEGRAM_GROUP_ID, TELEGRAM_TOPIC_*) переезжает в «Филиал 1»."""

import os

from django.db import migrations, models


def move_env_group(apps, schema_editor):
    """Если в .env уже вписана группа — записать её первому филиалу (чтобы ничего не настраивать заново)."""
    first = apps.get_model("cafe", "Branch").objects.order_by("position", "id").first()
    if first is None or first.tg_group_id:
        return
    number = lambda name: int(os.getenv(name) or 0) or None          # пусто или 0 — не настроено
    first.tg_group_id = number("TELEGRAM_GROUP_ID")
    first.tg_topic_admins = number("TELEGRAM_TOPIC_ADMINS")
    first.tg_topic_kitchen = number("TELEGRAM_TOPIC_KITCHEN")
    first.tg_topic_hall = number("TELEGRAM_TOPIC_HALL")
    first.tg_topic_delivery = number("TELEGRAM_TOPIC_DELIVERY")
    first.tg_topic_reports = number("TELEGRAM_TOPIC_REPORTS")
    first.save()


class Migration(migrations.Migration):

    dependencies = [("cafe", "0002_branches")]

    operations = [
        migrations.AddField("branch", "tg_group_id", models.BigIntegerField(blank=True, null=True, verbose_name="Telegram: ID группы")),
        migrations.AddField("branch", "tg_topic_admins", models.BigIntegerField(blank=True, null=True, verbose_name="Тема «Админы»")),
        migrations.AddField("branch", "tg_topic_kitchen", models.BigIntegerField(blank=True, null=True, verbose_name="Тема «Кухня»")),
        migrations.AddField("branch", "tg_topic_hall", models.BigIntegerField(blank=True, null=True, verbose_name="Тема «Зал»")),
        migrations.AddField("branch", "tg_topic_delivery", models.BigIntegerField(blank=True, null=True, verbose_name="Тема «Доставка»")),
        migrations.AddField("branch", "tg_topic_reports", models.BigIntegerField(blank=True, null=True, verbose_name="Тема «Отчёты»")),
        migrations.RunPython(move_env_group, migrations.RunPython.noop),
    ]
