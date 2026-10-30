"""Заказ из гостевого Telegram-бота помнит чат гостя — туда бот шлёт статусы."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("orders", "0003_branches")]

    operations = [
        migrations.AddField("order", "guest_chat_id", models.BigIntegerField(blank=True, null=True, verbose_name="Telegram гостя")),
    ]
