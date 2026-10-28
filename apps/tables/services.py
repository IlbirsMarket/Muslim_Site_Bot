"""Логика для столов: создание картинки QR-кода."""

from io import BytesIO   # "файл в памяти": сохраняем картинку без записи на диск

import qrcode            # библиотека для QR-кодов


def build_qr_png(url: str) -> bytes:
    """Создаёт PNG-картинку QR-кода с адресом url и возвращает её байты."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,  # средняя защита: QR читается, даже если немного испачкан
        box_size=30,                                         # размер одного квадратика в пикселях
        border=2,                                            # белая рамка вокруг (в квадратиках)
    )
    qr.add_data(url)                     # какой адрес зашиваем
    qr.make(fit=True)                    # подбираем размер QR под длину адреса
    image = qr.make_image(fill_color="black", back_color="white")  # чёрный QR на белом фоне
    buffer = BytesIO()                   # создаём "файл в памяти"
    image.save(buffer, format="PNG")     # сохраняем картинку в него
    return buffer.getvalue()             # отдаём байты картинки

def build_qr_sheet_pdf(tables) -> bytes:
    """PDF для печати: по 6 QR-кодов на листе A4, под каждым — название стола."""
    from reportlab.lib.pagesizes import A4          # размер листа
    from reportlab.lib.units import mm              # миллиметры
    from reportlab.lib.utils import ImageReader     # вставка картинки из памяти
    from reportlab.pdfgen import canvas             # "холст" для рисования

    from apps.reports.pdf import _register_fonts    # тот же шрифт с русскими буквами, что и в отчётах

    _register_fonts()
    buffer = BytesIO()                               # PDF собираем в памяти
    page = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4                              # ширина и высота листа
    card_w, card_h, qr_size = 90 * mm, 88 * mm, 60 * mm   # размер карточки и QR

    for index, table in enumerate(tables):
        position = index % 6                         # место на листе: 0–5
        if position == 0 and index > 0:              # 7-й, 13-й... стол — новый лист
            page.showPage()
        col, row = position % 2, position // 2       # 2 колонки × 3 ряда
        x = 15 * mm + col * (card_w + 5 * mm)        # левый край карточки
        top = page_h - 15 * mm - row * (card_h + 4 * mm)   # верхний край карточки

        page.setStrokeColorRGB(0.85, 0.83, 0.78)     # светлая рамка для вырезания
        page.roundRect(x, top - card_h, card_w, card_h, 4 * mm)
        qr_image = ImageReader(BytesIO(build_qr_png(table.qr_url)))   # картинка QR этого стола
        page.drawImage(qr_image, x + (card_w - qr_size) / 2, top - 8 * mm - qr_size, qr_size, qr_size)
        page.setFont("Main-Bold", 15)
        page.drawCentredString(x + card_w / 2, top - qr_size - 16 * mm, str(table))          # "Стол 7"
        page.setFont("Main", 9)
        page.drawCentredString(x + card_w / 2, top - qr_size - 22 * mm, "Наведите камеру, чтобы открыть меню")

    page.save()                                      # завершаем документ
    return buffer.getvalue()