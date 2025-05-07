from django.db import models
from django.contrib.auth.models import User
from projects.models import Project
from django.db.models.signals import pre_save
from django.dispatch import receiver


class Task(models.Model):
    """
    Модель для хранения задач проекта
    """
    # Статусы задачи для канбан-доски
    STATUS_CHOICES = (
        ('Новая', 'Новая'),
        ('В работе', 'В работе'),
        ('На проверке', 'На проверке'),
        ('Завершена', 'Завершена'),
    )

    # Приоритеты задачи
    PRIORITY_CHOICES = (
        ('Критический', 'Критический'),
        ('Высокий', 'Высокий'),
        ('Средний', 'Средний'),
        ('Низкий', 'Низкий'),
        ('Без приоритета', 'Без приоритета'),
    )

    # Основная информация о задаче
    title = models.CharField(max_length=200, verbose_name="Заголовок")
    description = models.TextField(blank=True, verbose_name="Описание")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Новая',
        verbose_name="Статус"
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='Без приоритета',
        verbose_name="Приоритет"
    )

    # Связи с проектом и пользователями
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='tasks',
        verbose_name="Проект"
    )
    assignee = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks',
        verbose_name="Исполнитель"
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_tasks',
        verbose_name="Создатель"
    )

    # Даты
    due_date = models.DateTimeField(null=True, blank=True, verbose_name="Срок выполнения")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    # Поле для связи с Google Calendar
    google_calendar_event_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="ID события в Google Calendar"
    )

    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def is_overdue(self):
        """Проверка, просрочена ли задача"""
        from django.utils import timezone
        if self.due_date and self.status != 'Завершена':
            return self.due_date < timezone.now()
        return False

    @property
    def comments_count(self):
        """Возвращает количество комментариев к задаче"""
        return self.comments.count()


class Comment(models.Model):
    """
    Модель для хранения комментариев к задачам
    """
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name="Задача"
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='task_comments',
        verbose_name="Автор"
    )
    text = models.TextField(verbose_name="Текст комментария")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Комментарий"
        verbose_name_plural = "Комментарии"
        ordering = ['created_at']

    def __str__(self):
        return f"Комментарий от {self.author.username} к задаче {self.task.id}"


@receiver(pre_save, sender=Task)
def update_google_calendar_event(sender, instance, **kwargs):
    """
    Обновляет событие в Google Calendar при изменении задачи
    """
    if not instance.id:
        # Пропускаем для новых задач
        return

    try:
        # Получаем оригинальную задачу из базы данных
        original_task = Task.objects.get(id=instance.id)

        # Проверяем, изменился ли срок выполнения
        if (original_task.due_date != instance.due_date and
                instance.google_calendar_event_id and
                instance.assignee and
                hasattr(instance.assignee, 'profile') and
                instance.assignee.profile.google_calendar_token):

            # Импортируем необходимые библиотеки
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from django.conf import settings
            from datetime import timedelta

            # Получаем профиль пользователя
            user_profile = instance.assignee.profile

            # Создаем объект credentials из сохраненных токенов
            credentials = Credentials(
                token=user_profile.google_calendar_token,
                refresh_token=user_profile.google_calendar_refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                scopes=['https://www.googleapis.com/auth/calendar']
            )

            # Создаем сервис Google Calendar
            service = build('calendar', 'v3', credentials=credentials)

            try:
                # Получаем событие
                event = service.events().get(
                    calendarId='primary',
                    eventId=instance.google_calendar_event_id
                ).execute()

                # Обновляем время начала и окончания
                start_time = instance.due_date
                end_time = start_time + timedelta(hours=1)

                event['start']['dateTime'] = start_time.isoformat()
                event['end']['dateTime'] = end_time.isoformat()

                # Обновляем заголовок и описание
                event['summary'] = f"[ProjectFlow] {instance.title}"
                event['description'] = instance.description or "Без описания"

                # Обновляем событие
                service.events().update(
                    calendarId='primary',
                    eventId=instance.google_calendar_event_id,
                    body=event
                ).execute()
            except Exception as inner_e:
                print(f"Ошибка при получении или обновлении события: {str(inner_e)}")

    except Exception as e:
        # Логируем ошибку, но не прерываем сохранение
        print(f"Ошибка при обновлении события в Google Calendar: {str(e)}")