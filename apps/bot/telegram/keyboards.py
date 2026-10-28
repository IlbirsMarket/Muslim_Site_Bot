"""Кнопки бота."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup   # кнопки под полем ввода

LOGIN = "🔑 Войти как сотрудник"      # тексты кнопок: по ним бот понимает, что нажали
MENU = "📋 Меню кафе"
PROFILE = "👤 Мой профиль"
LOGOUT = "🚪 Выйти"
CANCEL = "✖️ Отмена"


def main_keyboard(logged_in: bool) -> ReplyKeyboardMarkup:
    """Главные кнопки: до входа — «Войти» и «Меню», после — «Профиль», «Меню», «Выйти»."""
    if logged_in:
        rows = [[KeyboardButton(text=PROFILE), KeyboardButton(text=MENU)], [KeyboardButton(text=LOGOUT)]]
    else:
        rows = [[KeyboardButton(text=LOGIN)], [KeyboardButton(text=MENU)]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Во время входа — только «Отмена»."""
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True)