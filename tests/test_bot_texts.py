"""
Тексты бота: кто пишет, приветствие, профиль, меню (без Telegram).
Запуск: python manage.py test tests.test_bot_texts -v 2
"""

from apps.bot import texts
from apps.bot.services import login_from_telegram
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest    # общая подготовка: сотрудники, меню, столы


class BotTextsTests(BaseAPITest):

    def test_staff_by_telegram(self):
        self.assertIsNone(texts.staff_by_telegram(555))                      # ещё не вошёл
        login_from_telegram("waiter", PASSWORD, 555)
        self.assertEqual(texts.staff_by_telegram(555), self.waiter)          # вошёл
        User.objects.filter(pk=self.waiter.pk).update(is_active=False)
        self.assertIsNone(texts.staff_by_telegram(555))                      # заблокированный — как не вошёл

    def test_welcome_and_profile(self):
        self.assertIn("Войти как сотрудник", texts.welcome_text(None))       # гостю — как войти
        self.waiter.first_name = "Нурлан <b>"
        self.assertIn("Нурлан &lt;b&gt;", texts.welcome_text(self.waiter))   # имя безопасно для HTML
        self.assertIn("Официант", texts.welcome_text(self.waiter))
        self.assertIn("Логин: waiter", texts.profile_text(self.waiter))

    def test_menu_text(self):
        text = "\n".join(texts.menu_parts())
        self.assertIn("Пиццы", text)
        self.assertIn("Пепперони — от 550 сом", text)                        # с размерами — «от»
        self.assertIn("Чизбургер — 390 сом", text)
        self.assertIn("Стоп-блюдо — 300 сом — <i>нет в наличии</i>", text)   # стоп-лист виден
        self.pizzas.is_active = False
        self.pizzas.save()
        self.assertNotIn("Пиццы", "\n".join(texts.menu_parts()))             # скрытая категория не видна

    def test_money(self):
        self.assertEqual(texts.money(1500), "1 500 сом")