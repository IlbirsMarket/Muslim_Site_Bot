"""
Автоматическая защита при изменении сотрудника (срабатывает везде: панель кафе, Django-админка, команды).
  - заблокировали или сменили пароль → все входы на сайте отменяются, Telegram отвязывается;
  - сменили роль → все входы на сайте отменяются (сотрудник войдёт заново уже с новой ролью).
"""

from django.db.models.signals import post_save, pre_save   # «перед сохранением» и «после сохранения»
from django.dispatch import receiver                       # подписка на эти события

from .models import User
from .services import end_all_sessions                     # отменить все входы сотрудника


@receiver(pre_save, sender=User)
def remember_old_values(sender, instance, **kwargs):
    """Перед сохранением запоминаем, какими были пароль, блокировка и роль в базе."""
    old = User.objects.filter(pk=instance.pk).values("password", "is_active", "role").first() if instance.pk else None
    instance._security_old = old                           # у нового сотрудника — None (сравнивать не с чем)


@receiver(post_save, sender=User)
def end_sessions_on_change(sender, instance, created, **kwargs):
    """После сохранения: если изменилось важное для безопасности — отменяем входы."""
    old = getattr(instance, "_security_old", None)
    if created or not old:                                 # новый сотрудник — входов у него ещё нет
        return
    password_changed = old["password"] != instance.password          # новый пароль
    blocked = old["is_active"] and not instance.is_active             # только что заблокировали
    role_changed = old["role"] != instance.role                       # новая роль
    if password_changed or blocked or role_changed:
        end_all_sessions(instance)                         # все ключи продления — в чёрный список
    if (password_changed or blocked) and instance.telegram_id:
        User.objects.filter(pk=instance.pk).update(telegram_id=None)  # бот: войти заново логином и новым паролем
        instance.telegram_id = None                        # и в этом объекте тоже
