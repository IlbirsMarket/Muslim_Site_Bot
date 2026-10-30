"""Создание PDF-отчётов (библиотека reportlab)."""

from xml.sax.saxutils import escape     # название филиала безопасно вставляем в PDF (там разметка)
from io import BytesIO                                     # "файл в памяти"

from django.conf import settings                           # путь к проекту
from reportlab.lib import colors                           # цвета
from reportlab.lib.pagesizes import A4                     # размер листа
from reportlab.lib.styles import ParagraphStyle            # стили текста
from reportlab.lib.units import mm                         # миллиметры
from reportlab.pdfbase import pdfmetrics                   # регистрация шрифтов
from reportlab.pdfbase.ttfonts import TTFont               # шрифты TTF
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # блоки документа

FONT_DIR = settings.BASE_DIR / "core" / "fonts"           # где лежат шрифты
GREEN = colors.HexColor("#1F3D2B")                         # фирменный зелёный
LIGHT = colors.HexColor("#EEF3EE")                         # светлый фон заголовков таблиц
LINE = colors.HexColor("#D9D4C7")                          # цвет линий таблиц

_fonts_ready = False                                       # шрифты регистрируем один раз


def _register_fonts():
    """Подключаем шрифт с русскими буквами."""
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont("Main", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("Main-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    _fonts_ready = True


def _styles() -> dict:
    """Стили: заголовок, подзаголовок, обычный текст."""
    return {
        "title": ParagraphStyle("title", fontName="Main-Bold", fontSize=18, leading=22, textColor=GREEN),
        "h": ParagraphStyle("h", fontName="Main-Bold", fontSize=12, leading=16, spaceBefore=10, spaceAfter=6),
        "text": ParagraphStyle("text", fontName="Main", fontSize=10, leading=14, textColor=colors.HexColor("#5E5A50")),
    }


def _money(value) -> str:
    """52400 → '52 400 сом'"""
    return f"{value or 0:,}".replace(",", " ") + " сом"


def _table(rows, widths) -> Table:
    """Таблица в нашем стиле: первая строка — заголовок."""
    table = Table(rows, colWidths=widths)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Main"),            # шрифт всех ячеек
        ("FONTNAME", (0, 0), (-1, 0), "Main-Bold"),        # жирный заголовок
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),            # фон заголовка
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),             # линии
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),              # числа — по правому краю
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _summary_blocks(data, s) -> list:
    """Общие блоки для дневного отчёта и отчёта за период."""
    blocks = []

    # Главные цифры
    blocks.append(_table([
        ["Показатель", "Значение"],
        ["Выручка", _money(data["revenue"])],
        ["Завершённых заказов", data["orders_count"]],
        ["Средний чек", _money(data["avg_check"])],
        ["Отменено", data["cancelled_count"]],
        ["Ещё в работе", data["in_progress_count"]],
    ], [90 * mm, 70 * mm]))

    # Зал / доставка / самовывоз
    blocks.append(Paragraph("Откуда выручка", s["h"]))
    rows = [["Тип", "Заказов", "Выручка"]]
    rows += [[v["label"], v["count"], _money(v["revenue"])] for v in data["by_kind"].values()]
    blocks.append(_table(rows, [70 * mm, 40 * mm, 50 * mm]))

    # Оплата
    blocks.append(Paragraph("Оплата", s["h"]))
    rows = [["Способ", "Заказов", "Сумма"]]
    rows += [[v["label"], v["count"], _money(v["revenue"])] for v in data["by_payment"].values()]
    blocks.append(_table(rows, [70 * mm, 40 * mm, 50 * mm]))

    # Топ блюд
    blocks.append(Paragraph("Что продалось лучше всего", s["h"]))
    rows = [["Блюдо", "Продано, шт.", "Выручка"]]
    rows += [[d["name"], d["quantity"], _money(d["revenue"])] for d in data["top_dishes"]] or [["—", "", ""]]
    blocks.append(_table(rows, [80 * mm, 35 * mm, 45 * mm]))

    # Причины отмен
    if data["cancel_reasons"]:
        blocks.append(Paragraph("Причины отмен", s["h"]))
        rows = [["Причина", "Сколько"]] + [[r["reason"], r["count"]] for r in data["cancel_reasons"]]
        blocks.append(_table(rows, [120 * mm, 40 * mm]))
    return blocks


def _build(story) -> bytes:
    """Собираем PDF из блоков и возвращаем байты файла."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    doc.build(story)
    return buffer.getvalue()


def render_day_pdf(data) -> bytes:
    """PDF отчёта за день."""
    _register_fonts()
    s = _styles()
    story = [
        Paragraph("Муслим — отчёт за день", s["title"]),
        Paragraph(f"{escape(data.get('branch_name') or '')} · {data['date']:%d.%m.%Y}", s["text"]),   # филиал и дата
        Spacer(1, 8 * mm),
        *_summary_blocks(data, s),
        Paragraph("Выручка по часам", s["h"]),
        _table([["Час", "Заказов", "Выручка"]] + [[h["label"], h["count"], _money(h["revenue"])] for h in data["by_hour"]],
               [50 * mm, 40 * mm, 70 * mm]),
    ]
    return _build(story)


def render_period_pdf(data) -> bytes:
    """PDF отчёта за период 45 дней."""
    _register_fonts()
    s = _styles()
    p = data["period"]
    story = [
        Paragraph("Муслим — отчёт за 45 дней", s["title"]),
        Paragraph(f"{escape(data.get('branch_name') or '')} · {p['start_date']:%d.%m.%Y} — {p['end_date']:%d.%m.%Y} · день {p['day_number']} из {p['days_total']}", s["text"]),
        Spacer(1, 8 * mm),
        *_summary_blocks(data, s),
        Paragraph("Выручка по дням", s["h"]),
        _table([["Дата", "Заказов", "Выручка"]] + [[f"{d['date']:%d.%m.%Y}", d["count"], _money(d["revenue"])] for d in data["by_day"]],
               [50 * mm, 40 * mm, 70 * mm]),
    ]
    return _build(story)