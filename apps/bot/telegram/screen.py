"""
«Один экран»: у каждого чата одно сообщение бота, которое меняется при нажатии кнопок.
Текст ↔ текст и фото ↔ фото — редактируем. Текст ↔ фото Telegram не умеет —
тогда старое сообщение удаляется, новое появляется вместо него.
Где экран, хранится в состоянии чата (FSM): screen — id сообщения, screen_kind — "text" / "photo",
trash — лишние сообщения (например, PDF), которые удаляются при следующей смене экрана.
"""

from aiogram.exceptions import TelegramBadRequest           # «сообщение не найдено», «не изменилось» и т.п.
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

PHOTO_IDS = {}                                              # фото уже в Telegram: ключ → file_id (второй раз не загружаем)


def inline(rows) -> InlineKeyboardMarkup:
    """[[(текст, данные)], …] → клавиатура. Пустые ряды пропускаются."""
    rows = [[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows if row]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def delete(bot, chat_id, message_id) -> None:
    """Удалить сообщение; уже удалено или слишком старое — не страшно."""
    if message_id:
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramBadRequest:
            pass


async def drop_user_message(message) -> None:
    """Сообщение человека (логин, пароль, телефон…) — прочитали и убрали из чата."""
    await delete(message.bot, message.chat.id, message.message_id)


async def show(bot, chat_id, state, text, rows=(), photo=None, photo_key=None, current=None):
    """
    Показать экран. photo — файл для Telegram (тогда text — подпись), photo_key — ключ для запоминания file_id.
    current — сообщение, на котором нажали кнопку: если экран ещё не известен (бот перезапускали) — меняем его.
    """
    data = await state.get_data()
    for mid in data.get("trash", []):                       # лишние сообщения прошлого экрана
        await delete(bot, chat_id, mid)
    screen, kind = data.get("screen"), data.get("screen_kind")
    if not screen and current is not None:                   # после перезапуска бота — экран тот, где нажали
        screen, kind = current.message_id, "photo" if current.photo else "text"
    want = "photo" if photo is not None else "text"
    markup = inline(rows)
    sent = None
    if screen and kind == want:                              # тот же вид — просто меняем
        try:
            if want == "photo":
                sent = await bot.edit_message_media(InputMediaPhoto(media=PHOTO_IDS.get(photo_key) or photo, caption=text),
                                                    chat_id=chat_id, message_id=screen, reply_markup=markup)
            else:
                sent = await bot.edit_message_text(text, chat_id=chat_id, message_id=screen, reply_markup=markup)
        except TelegramBadRequest as error:
            if "not modified" in str(error):                 # ничего не изменилось — экран тот же
                sent = screen
            else:
                sent = None                                  # сообщение пропало — пришлём новое
    if sent is None:
        await delete(bot, chat_id, screen)                   # старый экран убираем
        if want == "photo":
            sent = await bot.send_photo(chat_id, PHOTO_IDS.get(photo_key) or photo, caption=text, reply_markup=markup)
        else:
            sent = await bot.send_message(chat_id, text, reply_markup=markup)
    message_id = screen if sent is True or isinstance(sent, int) else sent.message_id   # True — Telegram не вернул сообщение
    if photo_key and not isinstance(sent, (int, bool)) and getattr(sent, "photo", None):
        PHOTO_IDS[photo_key] = sent.photo[-1].file_id        # дальше это фото отправляется мгновенно
    await state.update_data(screen=message_id, screen_kind=want, trash=[])
    return message_id


async def forget_screen(state) -> None:
    """Экран стал «обычным» сообщением (например, статус заказа) — следующий экран будет новым сообщением."""
    await state.update_data(screen=None, screen_kind=None)


async def add_trash(state, message_id) -> None:
    """Сообщение удалится при следующей смене экрана."""
    data = await state.get_data()
    await state.update_data(trash=data.get("trash", []) + [message_id])
