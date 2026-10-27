"""
Вход по логину ИЛИ по email.
Django по умолчанию ищет сотрудника только по логину (username).
Этот «бэкенд» сначала ищет по логину, а если не нашёл и в тексте есть «@» — по email.
Работает везде: в панели /admin сайта, в API /api/auth/login/ и в Django-админке.
"""

from django.contrib.auth.backends import ModelBackend  # стандартная проверка логина и пароля

from .models import User                                # наша модель сотрудника


class EmailOrUsernameBackend(ModelBackend):
    """Проверяет пароль сотрудника, найденного по логину или по email."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:                                     # Django-админка может передать логин под другим именем
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or not password:                         # пустые поля — сразу отказ
            return None

        login = username.strip()                                 # убираем случайные пробелы по краям

        user = User.objects.filter(username=login).first()       # 1) ищем по логину (как раньше)
        if user is None and "@" in login:                        # 2) не нашли, а похоже на email
            user = User.objects.filter(email__iexact=login).first()  # ищем по email без учёта регистра

        if user is None:
            User().set_password(password)                        # тратим столько же времени, сколько на проверку пароля:
            return None                                          # так по скорости ответа нельзя угадать, есть ли такой email

        if user.check_password(password) and self.user_can_authenticate(user):  # пароль верный и аккаунт не заблокирован
            return user
        return None                                              # иначе — вход запрещён