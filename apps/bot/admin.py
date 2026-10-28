"""Таблицы бота в админке Django (чтобы видеть, что бот отправил и где ошибки)."""

from django.contrib import admin                        # админка Django

from .models import BotEvent, BotMessage, LinkCode      # наши таблицы


@admin.register(BotEvent)
class BotEventAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "order", "call", "table", "created_at", "processed_at", "attempts")  # колонки
    list_filter = ("kind",)                                                                            # фильтр по типу
    readonly_fields = ("created_at",)                                                                  # только смотреть


@admin.register(BotMessage)
class BotMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "place", "order", "call", "chat_id", "thread_id", "message_id", "updated_at")  # колонки
    list_filter = ("place",)                                                                             # фильтр по теме
    readonly_fields = ("created_at", "updated_at")                                                       # только смотреть


@admin.register(LinkCode)
class LinkCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "used_at")    # сам код в списке не показываем
    readonly_fields = ("code", "created_at")            # код и время менять нельзя