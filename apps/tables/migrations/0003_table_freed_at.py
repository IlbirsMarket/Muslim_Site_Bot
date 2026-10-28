# Время последнего «Освободить стол»: по нему гости за столом понимают, что стол закрыт

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0002_table_numbers_and_occupied"),
    ]

    operations = [
        migrations.AddField(
            model_name="table",
            name="freed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Освобождён"),
        ),
    ]