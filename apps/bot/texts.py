"""
Тексты бота и данные для них. Здесь нет Telegram — только база и строки,
поэтому всё это проверяется обычными тестами Django.
"""

from html import escape                          # имена и названия — безопасно для HTML в Telegram

from django.contrib.auth import get_user_model   # модель сотрудника
from django.db.models import Prefetch            # блюда категории одним запросом

from apps.cafe.models import Branch               # филиалы
from apps.menu.models import Category, Dish       # меню — то же, что на сайте

MESSAGE_LIMIT = 4000                             # Telegram принимает до 4096 символов — оставляем запас


def money(value) -> str:
    """1500 → «1 500 сом»."""
    return f"{value:,}".replace(",", " ") + " сом"


def staff_by_telegram(telegram_id: int):
    """Сотрудник с этим Telegram (активный и с ролью) или None — значит, ещё не вошёл."""
    return (
        get_user_model().objects.select_related("branch")                            # сразу с филиалом
        .filter(telegram_id=telegram_id, is_active=True).exclude(role="").first()
    )


def person(user) -> str:
    """Как обращаться к сотруднику: имя, а если его нет — логин."""
    return escape(user.first_name or user.username)


def welcome_text(user) -> str:
    """Первое сообщение после /start."""
    if user:                                                       # уже вошёл
        return (f"Ассаляму алейкум, {person(user)}!\n"
                f"Вы вошли как <b>{user.get_role_display()}</b>.\n\n"
                "Скоро здесь появятся заказы, столы и всё остальное, что есть в панели на сайте.")
    return ("Ассаляму алейкум! Это бот кафе «Муслим».\n\n"
            "Сотрудникам: нажмите «🔑 Войти как сотрудник» и введите логин и пароль от панели на сайте.\n"
            "Гостям: посмотрите «📋 Меню кафе».")


def profile_text(user) -> str:
    """«👤 Мой профиль»."""
    lines = [
        f"<b>{person(user)}</b>",
        f"Роль: {user.get_role_display()}",
        f"Филиал: {escape(user.branch.name) if user.branch_id else 'все филиалы'}",
        f"Логин: {escape(user.username)}",
    ]
    if user.phone:
        lines.append(f"Телефон: {escape(user.phone)}")
    lines.append("\nЧтобы отвязать этот Telegram, нажмите «🚪 Выйти».")
    return "\n".join(lines)


def menu_parts(branch=None) -> list:
    """Меню филиала текстом (как у гостей на сайте; без филиала — первый). Длинное меню делим на несколько сообщений."""
    branch = branch or Branch.default()
    dishes = Dish.objects.filter(is_active=True).prefetch_related("sizes")             # видимые блюда с размерами
    categories = Category.objects.filter(is_active=True, branch=branch).prefetch_related(
        Prefetch("dishes", queryset=dishes, to_attr="visible_dishes"),
    )
    blocks = []
    for category in categories:
        if not category.visible_dishes:                                                 # пустые категории не показываем
            continue
        rows = [f"<b>{escape(category.name)}</b>"]
        for dish in category.visible_dishes:
            price = f"от {money(dish.min_price)}" if dish.sizes.all() else money(dish.price)
            mark = "" if dish.is_available else " — <i>нет в наличии</i>"
            rows.append(f"• {escape(dish.name)} — {price}{mark}")
        blocks.append("\n".join(rows))
    if not blocks:
        return ["Меню пока пустое."]
    parts, current = [], f"📋 <b>Меню кафе «Муслим» · {escape(branch.name)}</b>"
    for block in blocks:                                                                # собираем сообщения не длиннее лимита
        if len(current) + len(block) + 2 > MESSAGE_LIMIT:
            parts.append(current)
            current = block
        else:
            current += "\n\n" + block
    parts.append(current)
    return parts