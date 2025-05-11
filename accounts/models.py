from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """
    Доп поля для юзера
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    # тут храним токены для гугл календаря
    google_calendar_token = models.TextField(null=True, blank=True)
    google_calendar_refresh_token = models.TextField(null=True, blank=True)
    google_calendar_token_expiry = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Профиль {self.user.username}"


# когда создается юзер - автоматом создаем профиль юзера и далее сохраняем
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()