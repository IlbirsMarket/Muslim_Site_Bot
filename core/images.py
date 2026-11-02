"""
Фото блюд: уменьшаем и переводим в WebP при загрузке.
Фото 2К на 2 МБ превращается примерно в 100–250 КБ — меню у гостей открывается в разы быстрее.
"""

from io import BytesIO                      # картинка в памяти
from pathlib import Path                    # имя файла без расширения

from django.core.files.base import ContentFile

MAX_SIDE = 1400                             # длинная сторона: хватает и для карточки, и для большого окна блюда
QUALITY = 80                                # качество WebP: на глаз как оригинал, а файл в разы меньше


def to_webp(uploaded) -> ContentFile:
    """Загруженный файл → ContentFile «имя.webp» (уменьшенный, без лишних данных из камеры)."""
    from PIL import Image, ImageOps
    uploaded.seek(0)
    image = ImageOps.exif_transpose(Image.open(uploaded))      # фото с телефона «лежит на боку» — поворачиваем как надо
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))                     # только уменьшаем, маленькие не растягиваем
    out = BytesIO()
    image.save(out, "WEBP", quality=QUALITY, method=6)
    name = Path(getattr(uploaded, "name", "photo") or "photo").stem[:80] + ".webp"
    return ContentFile(out.getvalue(), name=name)


def jpeg_bytes(path: str) -> bytes:
    """Для Telegram: WebP → JPEG в памяти (Telegram надёжнее всего показывает JPEG как фото)."""
    from PIL import Image
    with Image.open(path) as image:
        out = BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue()
