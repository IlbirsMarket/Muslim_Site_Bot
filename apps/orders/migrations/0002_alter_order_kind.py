# Четыре типа заказа: «В зале» и «С собой» (со стола), «Доставка» и «Самовывоз» (с главной страницы).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="kind",
            field=models.CharField(
                choices=[("hall", "В зале"), ("takeaway", "С собой"), ("delivery", "Доставка"), ("pickup", "Самовывоз")],
                max_length=10, verbose_name="Тип",
            ),
        ),
    ]