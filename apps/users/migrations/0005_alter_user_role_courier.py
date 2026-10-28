# Новая роль «Курьер»: меняется только список вариантов роли, данные в таблице не трогаем

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_user_unique_email"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("programmer", "Программист"), ("chef", "Шеф"), ("admin", "Админ"),
                    ("cook", "Повар"), ("waiter", "Официант"), ("courier", "Курьер"),
                ],
                max_length=20, verbose_name="Роль",
            ),
        ),
    ]