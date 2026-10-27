# Один email — один сотрудник (без учёта регистра). Пустой email разрешён у многих.

import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_rolechangelog"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                condition=models.Q(("email", ""), _negated=True),
                name="unique_user_email_ci",
                violation_error_message="Сотрудник с таким email уже есть.",
            ),
        ),
    ]