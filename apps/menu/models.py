"""
Таблицы меню:
Category — категория (Пиццы, Напитки)
Extra    — добавка (Сыр +80)
Dish     — блюдо (Пепперони)
DishSize — размер блюда со своей ценой (25 см — 550 сом)
"""

from django.db import models  # поля для таблиц

from apps.cafe.models import default_branch_id   # первый филиал — по умолчанию


class Category(models.Model):
    """Категория меню (у каждого филиала свои)."""

    branch = models.ForeignKey(                                             # филиал: у каждого своё меню
        "cafe.Branch", on_delete=models.PROTECT, related_name="categories", verbose_name="Филиал",
        default=default_branch_id,
    )
    name = models.CharField("Название", max_length=100)                    # например "Пиццы"
    position = models.PositiveIntegerField("Порядок", default=0)           # чем меньше, тем выше в меню
    is_active = models.BooleanField("Показывать в меню", default=True)     # скрыть категорию, не удаляя

    class Meta:
        ordering = ["position", "id"]          # порядок по умолчанию
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def __str__(self):
        return self.name                        # как отображается в админке


class Extra(models.Model):
    """Добавка к блюду (Сыр, Халапеньо). Одна добавка может подходить к разным блюдам своего филиала."""

    branch = models.ForeignKey(                                             # филиал: у каждого своё меню
        "cafe.Branch", on_delete=models.PROTECT, related_name="extras", verbose_name="Филиал",
        default=default_branch_id,
    )
    name = models.CharField("Название", max_length=100)                 # "Сыр моцарелла"
    price = models.PositiveIntegerField("Цена, сом")                     # доплата за добавку
    is_available = models.BooleanField("В наличии", default=True)      # закончилась — выключаем

    class Meta:
        ordering = ["name"]
        verbose_name = "Добавка"
        verbose_name_plural = "Добавки"

    def __str__(self):
        return f"{self.name} (+{self.price} сом)"


class Dish(models.Model):
    """Блюдо."""

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,               # нельзя удалить категорию, пока в ней есть блюда
        related_name="dishes",                  # category.dishes — все блюда категории
        verbose_name="Категория",
    )
    name = models.CharField("Название", max_length=150)                         # "Пепперони"
    description = models.TextField("Состав / описание", blank=True)             # "Халяль-колбаса, моцарелла..."
    photo = models.ImageField("Фото", upload_to="dishes/", blank=True)           # фото попадает в media/dishes/
    price = models.PositiveIntegerField("Цена, сом", default=0)                 # цена, если у блюда нет размеров
    extras = models.ManyToManyField(Extra, blank=True, related_name="dishes", verbose_name="Добавки")  # какие добавки можно выбрать
    is_available = models.BooleanField("В наличии", default=True)               # False = в стоп-листе ("Нет в наличии")
    is_active = models.BooleanField("Показывать в меню", default=True)          # False = блюдо скрыто совсем
    position = models.PositiveIntegerField("Порядок", default=0)                # порядок внутри категории
    created_at = models.DateTimeField("Создано", auto_now_add=True)             # ставится один раз при создании
    updated_at = models.DateTimeField("Изменено", auto_now=True)                # обновляется при каждом сохранении

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Блюдо"
        verbose_name_plural = "Блюда"

    def __str__(self):
        return self.name

    @property
    def min_price(self) -> int:
        """Минимальная цена для надписи «от 550 сом». Если размеров нет — обычная цена."""
        prices = [size.price for size in self.sizes.all()]  # цены всех размеров
        return min(prices) if prices else self.price        # самая маленькая или обычная цена


class DishSize(models.Model):
    """Размер блюда со своей ценой: 25 см — 550, 30 см — 650."""

    dish = models.ForeignKey(
        Dish,
        on_delete=models.CASCADE,               # удалили блюдо — удаляются и его размеры
        related_name="sizes",                   # dish.sizes — все размеры блюда
        verbose_name="Блюдо",
    )
    name = models.CharField("Размер", max_length=50)                 # "30 см", "0,5 л"
    price = models.PositiveIntegerField("Цена, сом")                  # цена этого размера
    position = models.PositiveIntegerField("Порядок", default=0)     # порядок кнопок размеров

    class Meta:
        ordering = ["position", "price"]
        verbose_name = "Размер"
        verbose_name_plural = "Размеры"

    def __str__(self):
        return f"{self.dish.name} — {self.name}"