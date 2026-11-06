"""
Поставить сотруднику код входа прямо на сервере (например, программисту или шефу в первый раз):
    python manage.py set_pin <логин>
Код спрашивается скрыто (не виден на экране и не попадает в историю команд).
"""

from getpass import getpass                                       # скрытый ввод

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.users.models import User
from apps.users.serializers import check_pin                      # те же правила: 2–8 цифр, не занят


class Command(BaseCommand):
    help = "Поставить сотруднику код входа в панель (от 2 до 8 цифр)."

    def add_arguments(self, parser):
        parser.add_argument("username", help="логин сотрудника")

    def handle(self, *args, **options):
        user = User.objects.filter(username__iexact=options["username"]).first()
        if user is None:
            raise CommandError("Сотрудник с таким логином не найден.")
        code = getpass("Новый код (цифры не видны): ").strip()
        if code != getpass("Повторите код: ").strip():
            raise CommandError("Коды не совпадают.")
        try:
            code = check_pin(code, user, required=True)
        except ValidationError as error:
            raise CommandError(" ".join(str(e) for e in error.detail))
        user.set_pin(code)
        user.save(update_fields=["pin_hash"])
        self.stdout.write(self.style.SUCCESS(f"Код для «{user.username}» сохранён."))
