"""
С каким филиалом работает запрос.

Сотрудник (админ, повар, официант, курьер) — всегда только со своим филиалом, что бы ни прислал фронт.
Шеф и программист выбирают филиал переключателем в панели: фронт присылает заголовок X-Branch: <id>
(или ?branch=<id>). Для отчётов шеф может выбрать «all» — оба филиала вместе.
Гость: филиал берётся из QR (стол / доставка) или из ?branch=<id> — только для просмотра меню.
"""

from rest_framework.exceptions import ValidationError    # ошибка 400 с понятным текстом

from apps.cafe.models import Branch

ALL = "all"                                              # «Оба филиала» — только в отчётах шефа


def _requested(request) -> str:
    """Что прислал фронт: заголовок X-Branch или ?branch=. Пусто — ничего не выбрано."""
    raw = request.headers.get("X-Branch") or request.query_params.get("branch") or ""
    return str(raw).strip()


def _find(raw: str) -> Branch:
    """Филиал по id из запроса. Неизвестный id — ошибка 400 (а не тихо «первый филиал»)."""
    if not raw.isdigit():
        raise ValidationError({"branch": "Неизвестный филиал."})
    branch = Branch.objects.filter(pk=int(raw), is_active=True).first()
    if branch is None:
        raise ValidationError({"branch": "Неизвестный филиал."})
    return branch


def staff_branch(request, allow_all: bool = False):
    """
    Филиал для сотрудника. Возвращает Branch, а для шефа с «all» (если allow_all) — None (оба филиала).
    Результат запоминается в запросе: внутри одного запроса филиал не меняется.
    """
    cache_key = "_branch_all" if allow_all else "_branch"
    if hasattr(request, cache_key):
        return getattr(request, cache_key)
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and not user.sees_all_branches():
        branch = user.branch or Branch.default()         # свой филиал; на всякий случай — первый
    else:
        raw = _requested(request)
        if allow_all and raw == ALL:
            branch = None                                # шеф смотрит оба филиала
        else:
            branch = _find(raw) if raw else Branch.default()
    setattr(request, cache_key, branch)
    return branch


def guest_branch(request) -> Branch:
    """
    Филиал для гостя (меню, настройки):
      ?token=<QR стола или доставки> — филиал этого QR;
      ?branch=<id> — выбранный в переключателе на главной (только посмотреть меню);
      иначе — первый филиал.
    """
    from apps.tables.models import Table                 # импорт здесь: столы сами зависят от филиалов

    token = str(request.query_params.get("token") or "").strip()
    if token:
        table = Table.objects.select_related("branch").filter(token=token, is_active=True).first()
        if table is not None:
            return table.branch
    raw = _requested(request)
    return _find(raw) if raw else Branch.default()


class BranchScopedMixin:
    """
    Для ViewSet'ов панели: список и поиск по id — только в текущем филиале,
    новые записи создаются в текущем филиале.
    branch_lookup — путь к филиалу от модели: "branch", "category__branch", "dish__category__branch".
    """

    branch_lookup = "branch"                              # по умолчанию у модели есть поле branch

    @property
    def branch(self):
        """Текущий филиал запроса."""
        return staff_branch(self.request)

    def get_queryset(self):
        return super().get_queryset().filter(**{self.branch_lookup: self.branch})

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "request", None) is not None:   # Swagger строит схему без запроса
            context["branch"] = self.branch               # сериализатор проверит, что ссылки — из этого филиала
        return context

    def perform_create(self, serializer):
        if self.branch_lookup == "branch":                # у модели своё поле филиала
            serializer.save(branch=self.branch)
        else:                                             # филиал задаётся через связь (категория, блюдо)
            serializer.save()


def check_same_branch(obj, branch, message="Это из другого филиала."):
    """Ссылка (категория, добавка, блюдо) должна быть из текущего филиала."""
    if obj is not None and branch is not None and obj.branch_id != branch.id:
        raise ValidationError(message)
