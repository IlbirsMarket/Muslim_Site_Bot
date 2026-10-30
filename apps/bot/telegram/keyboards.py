"""Кнопки бота."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup   # кнопки под полем ввода

LOGIN = "🔑 Войти как сотрудник"      # тексты кнопок: по ним бот понимает, что нажали
MENU = "📋 Меню кафе"
PROFILE = "👤 Мой профиль"
LOGOUT = "🚪 Выйти"
CANCEL = "✖️ Отмена"
STOP = "🛑 Стоп-лист"                 # повар (и админ): включить / выключить блюда
TABLES = "🍽 Занятые столы"           # официант (и админ): освободить стол
REPORT = "📊 Отчёт за день"           # админ, шеф, программист


def role_buttons(user) -> list:
    """Кнопки по роли сотрудника."""
    if user is None or user is True:                     # роль неизвестна — без дополнительных кнопок
        return []
    buttons = []
    if user.is_cook or user.is_cafe_admin:
        buttons.append(KeyboardButton(text=STOP))
    if user.is_waiter or user.is_cafe_admin:
        buttons.append(KeyboardButton(text=TABLES))
    if user.is_cafe_admin or user.sees_all_branches():
        buttons.append(KeyboardButton(text=REPORT))
    return buttons


def main_keyboard(logged_in, user=None) -> ReplyKeyboardMarkup:
    """Главные кнопки: до входа — «Войти» и «Меню», после — кнопки роли, «Профиль», «Меню», «Выйти»."""
    if logged_in:
        rows = [[KeyboardButton(text=PROFILE), KeyboardButton(text=MENU)], [KeyboardButton(text=LOGOUT)]]
        extra = role_buttons(user)                       # стоп-лист / столы / отчёт
        if extra:
            rows.insert(0, extra)
    else:
        rows = [[KeyboardButton(text=LOGIN)], [KeyboardButton(text=MENU)]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Во время входа — только «Отмена»."""
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True)