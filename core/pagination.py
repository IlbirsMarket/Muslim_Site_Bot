"""Разбивка списков на страницы — только если фронт попросил (?page=1)."""

from rest_framework.pagination import PageNumberPagination   # стандартные страницы DRF


class OptionalPageNumberPagination(PageNumberPagination):
    page_size = 30                       # по 30 записей на страницу
    page_size_query_param = "page_size"  # фронт может попросить ?page_size=50
    max_page_size = 100                  # но не больше 100

    def paginate_queryset(self, queryset, request, view=None):
        if "page" not in request.query_params:   # ?page нет — отдаём весь список, как раньше
            return None
        return super().paginate_queryset(queryset, request, view)