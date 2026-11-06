"""
Код входа больше не хранится открыто: поле pin (2 цифры) → pin_hash (отпечаток HMAC, код от 2 до 8 цифр).
Уже заданные коды переносятся: из кода считается отпечаток, сам код удаляется.
"""

from django.db import migrations, models


def codes_to_hashes(apps, schema_editor):
    """Каждый заданный код → его отпечаток (как в apps/users/pin_login.py)."""
    from apps.users.pin_login import pin_hash
    User = apps.get_model("users", "User")
    for user in User.objects.exclude(pin__isnull=True).exclude(pin=""):
        user.pin_hash = pin_hash(user.pin)
        user.save(update_fields=["pin_hash"])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_pin_login"),
    ]

    operations = [
        migrations.AddField(                                   # 1. новое поле — отпечаток кода
            model_name="user",
            name="pin_hash",
            field=models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True,
                                   verbose_name="Код входа (отпечаток)"),
        ),
        migrations.RunPython(codes_to_hashes, migrations.RunPython.noop),   # 2. переносим заданные коды
        migrations.RemoveField(model_name="user", name="pin"),              # 3. открытые коды удаляем
    ]
