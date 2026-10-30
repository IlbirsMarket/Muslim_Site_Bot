"""Гостевой бот отмечает свои события отдельно от служебного (у каждого своя отметка «отправлено»)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("bot", "0001_initial")]

    operations = [
        migrations.AddField("botevent", "guest_processed_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Гостю отправлено")),
    ]
