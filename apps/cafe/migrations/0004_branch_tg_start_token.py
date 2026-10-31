"""Секретный код ссылки на гостевой бот у каждого филиала (для QR «Telegram-бот» и кнопки «Обновить QR»)."""

import secrets

from django.db import migrations, models


def fill_tokens(apps, schema_editor):
    """Уже существующим филиалам — каждому свой код."""
    Branch = apps.get_model("cafe", "Branch")
    for branch in Branch.objects.all():
        branch.tg_start_token = secrets.token_urlsafe(9)
        branch.save(update_fields=["tg_start_token"])


class Migration(migrations.Migration):

    dependencies = [("cafe", "0003_branch_telegram")]

    operations = [
        migrations.AddField(
            model_name="branch", name="tg_start_token",
            field=models.CharField(blank=True, editable=False, max_length=32, verbose_name="Код ссылки на гостевой бот"),
        ),
        migrations.RunPython(fill_tokens, migrations.RunPython.noop),
    ]
