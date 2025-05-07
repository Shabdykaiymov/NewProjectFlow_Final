from rest_framework import views, status, permissions
from rest_framework.response import Response
from django.shortcuts import redirect
from django.conf import settings
from datetime import datetime, timedelta
from .services import GoogleCalendarService
from accounts.models import UserProfile
from django.http import HttpResponse
import logging

# Настраиваем логгер
logger = logging.getLogger('newprojectflowapp')


class GoogleAuthURLView(views.APIView):
    """
    Представление для получения URL для авторизации в Google Calendar
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Получаем ID задачи из запроса, если есть
        task_id = request.query_params.get('task_id')
        if task_id:
            # Сохраняем ID задачи в сессии
            request.session['after_auth_task_id'] = task_id
            request.session.save()
            logger.info(f"Сохранен ID задачи {task_id} в сессии для последующей синхронизации")

        auth_url, state = GoogleCalendarService.get_authorization_url(request)

        # Сохраняем состояние в сессии для проверки при callback
        request.session['google_auth_state'] = state
        logger.info(f"Сохраняем состояние в сессии: {state}")

        # Явно сохраняем сессию
        request.session.save()

        response = Response({'auth_url': auth_url})

        # Сохраняем ID пользователя в cookie для использования при callback
        response.set_cookie('user_id', request.user.id, max_age=3600)  # 1 час

        return response


class GoogleAuthCallbackView(views.APIView):
    """
    Представление для обработки callback от Google OAuth2
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        code = request.GET.get('code')
        state = request.GET.get('state')
        session_state = request.session.get('google_auth_state')

        logger.info(
            f"Получен callback от Google OAuth2. Полученное состояние: {state}, Состояние в сессии: {session_state}")

        # Используем cookie вместо сессии для хранения user_id
        current_user = None

        # Сначала пробуем получить user_id из cookie
        user_id = request.COOKIES.get('user_id')
        if user_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                current_user = User.objects.get(id=user_id)
                logger.info(f"Пользователь найден из cookie: {current_user.username}")
            except User.DoesNotExist:
                logger.warning(f"Пользователь с ID {user_id} не найден")

        # Если не нашли пользователя, ищем по сохраненному state
        if not current_user and state and session_state and state == session_state:
            # Ищем пользователя, который инициировал авторизацию
            try:
                # Проверяем все профили, где есть этот state
                from accounts.models import UserProfile
                # Здесь можно добавить логику поиска пользователя по state
                # Но это сложнее, поэтому используем другой подход
                pass
            except Exception as e:
                logger.error(f"Ошибка при поиске пользователя: {str(e)}")

        if not current_user:
            logger.error("Не удалось определить пользователя при callback")
            # Создаем ответ с инструкцией для пользователя
            return HttpResponse(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Ошибка авторизации</title>
                <script>
                    // Сохраняем данные в localStorage для повторной авторизации
                    localStorage.setItem('google_auth_code', '{code}');
                    localStorage.setItem('google_auth_state', '{state}');

                    alert('Ошибка авторизации. Пожалуйста, войдите в систему.');
                    setTimeout(function() {{
                        window.location.href = '/login/';
                    }}, 2000);
                </script>
            </head>
            <body>
                <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                    <h2>Ошибка авторизации Google Calendar</h2>
                    <p>Произошла ошибка при авторизации. Перенаправление на страницу входа...</p>
                </div>
            </body>
            </html>
            """, content_type='text/html; charset=utf-8')

        # Обмениваем код на токены
        try:
            token_info = GoogleCalendarService.exchange_code_for_token(code)
            logger.info(f"Успешно получены токены для пользователя {current_user.username}")

            # Сохраняем токены в профиле пользователя
            user_profile = current_user.profile
            user_profile.google_calendar_token = token_info['token']
            user_profile.google_calendar_refresh_token = token_info.get('refresh_token')

            if token_info.get('expiry'):
                user_profile.google_calendar_token_expiry = datetime.fromisoformat(token_info['expiry'])

            user_profile.save()
            logger.info(f"Токены сохранены для пользователя {current_user.username}")

            # Проверяем, был ли сохранен ID задачи перед авторизацией
            task_id = request.session.get('after_auth_task_id')
            if task_id:
                logger.info(f"Найден ID задачи {task_id} в сессии для синхронизации")

                # Удаляем ID задачи из сессии
                del request.session['after_auth_task_id']
                request.session.save()

                # Перенаправляем на страницу проекта с информацией о задаче
                from tasks.models import Task
                try:
                    task = Task.objects.get(id=task_id)
                    project_id = task.project.id
                    logger.info(f"Задача {task_id} найдена, принадлежит проекту {project_id}")

                    # Простой и надежный JavaScript для синхронизации
                    sync_script = f"""
                    <script>
                        function syncTask() {{
                            console.log('Начинаем синхронизацию задачи {task_id}');

                            // Получаем актуальный токен 
                            const token = localStorage.getItem('access_token');
                            if (!token) {{
                                console.error('Токен авторизации не найден!');
                                alert('Ошибка: Токен авторизации не найден. Пожалуйста, войдите снова.');
                                return;
                            }}

                            // Показываем индикатор загрузки
                            document.body.innerHTML += '<div id="sync-loader" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center;"><div style="background: white; padding: 20px; border-radius: 5px;">Синхронизация с Google Calendar...</div></div>';

                            fetch('/api/tasks/{task_id}/sync_calendar/', {{
                                method: 'POST',
                                headers: {{
                                    'Content-Type': 'application/json',
                                    'Authorization': 'Bearer ' + token
                                }},
                                body: JSON.stringify({{}})
                            }})
                            .then(response => {{
                                console.log('Статус ответа:', response.status);
                                if (!response.ok) {{
                                    throw new Error('Ошибка HTTP: ' + response.status);
                                }}
                                return response.json().catch(e => {{
                                    console.error('Ошибка парсинга JSON:', e);
                                    throw new Error('Невозможно прочитать ответ от сервера');
                                }});
                            }})
                            .then(data => {{
                                console.log('Данные ответа:', data);
                                // Удаляем индикатор загрузки
                                document.getElementById('sync-loader').remove();

                                if (data.status === 'success') {{
                                    alert(data.message);
                                    if (data.event_link) {{
                                        if (confirm('Событие создано. Хотите открыть его в Google Calendar?')) {{
                                            window.open(data.event_link, '_blank');
                                        }}
                                    }}
                                }} else {{
                                    alert('Ошибка при синхронизации: ' + (data.message || 'Неизвестная ошибка'));
                                }}
                            }})
                            .catch(error => {{
                                // Удаляем индикатор загрузки
                                if (document.getElementById('sync-loader')) {{
                                    document.getElementById('sync-loader').remove();
                                }}

                                console.error('Ошибка при синхронизации:', error);
                                alert('Ошибка при синхронизации с Google Calendar: ' + error.message);
                            }});
                        }}

                        // Выполняем синхронизацию с небольшой задержкой после загрузки страницы
                        document.addEventListener('DOMContentLoaded', function() {{
                            alert('Авторизация в Google Calendar успешно завершена! Сейчас задача будет синхронизирована.');
                            setTimeout(syncTask, 1000);
                        }});
                    </script>
                    """

                    # Перенаправляем на страницу проекта
                    logger.info(f"Отправляем HTML с JavaScript для автоматической синхронизации")
                    return HttpResponse(f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <title>Перенаправление...</title>
                        <meta http-equiv="refresh" content="7; url=/projects/{project_id}/">
                        {sync_script}
                    </head>
                    <body>
                        <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                            <h2>Авторизация в Google Calendar успешна!</h2>
                            <p>Выполняется синхронизация задачи...</p>
                            <p>Перенаправление на страницу проекта через 7 секунд...</p>
                        </div>
                    </body>
                    </html>
                    """, content_type='text/html; charset=utf-8')

                except Task.DoesNotExist:
                    logger.warning(f"Задача {task_id} не найдена в базе данных")
                except Exception as e:
                    logger.error(f"Ошибка при обработке перенаправления: {str(e)}")

                # Если возникла ошибка, просто перенаправляем на страницу проекта
                logger.info("Перенаправление на страницу проектов")
                return redirect('/projects/')

            # Перенаправляем на страницу успеха
            logger.info("Перенаправление на страницу успеха")
            return redirect('/api/calendar/success/')

        except Exception as e:
            logger.error(f"Ошибка при обработке callback: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class GoogleCalendarSuccessView(views.APIView):
    """
    Представление для подтверждения успешной авторизации
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Изначально проверяем токены авторизации пользователя
        user_profile = request.user.profile
        if user_profile.google_calendar_token:
            # Проверяем, есть ли ID задачи в URL параметрах
            task_id = request.query_params.get('task_id') or request.session.get('after_auth_task_id')

            # Если не находим ID в параметрах или сессии, показываем приветственную страницу
            if not task_id:
                logger.info(f"ID задачи не найден, показываем страницу успешной авторизации")
                return HttpResponse("""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <title>Google Calendar подключен</title>
                    <meta http-equiv="refresh" content="3; url=/projects/">
                    <style>
                        body { text-align: center; font-family: Arial, sans-serif; padding-top: 100px; }
                        .success { color: green; font-size: 24px; }
                        .redirect { margin-top: 20px; font-style: italic; }
                    </style>
                </head>
                <body>
                    <div class="success">
                        ✅ Авторизация в Google Calendar успешно завершена!
                    </div>
                    <div class="redirect">
                        Перенаправление на страницу проектов через 3 секунды...
                    </div>
                </body>
                </html>
                """, content_type='text/html; charset=utf-8')

            try:
                from tasks.models import Task
                task = Task.objects.get(id=task_id)
                project_id = task.project.id
                logger.info(f"Найдена задача {task_id} для синхронизации, принадлежит проекту {project_id}")

                # Удаляем ID задачи из сессии, если он там есть
                if 'after_auth_task_id' in request.session:
                    del request.session['after_auth_task_id']
                    request.session.save()

                # Простой и надежный JavaScript для синхронизации
                sync_script = f"""
                <script>
                    function syncTask() {{
                        console.log('Начинаем синхронизацию задачи {task_id}');

                        // Получаем актуальный токен 
                        const token = localStorage.getItem('access_token');
                        if (!token) {{
                            console.error('Токен авторизации не найден!');
                            alert('Ошибка: Токен авторизации не найден. Пожалуйста, войдите снова.');
                            return;
                        }}

                        // Показываем индикатор загрузки
                        document.body.innerHTML += '<div id="sync-loader" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center;"><div style="background: white; padding: 20px; border-radius: 5px;">Синхронизация с Google Calendar...</div></div>';

                        fetch('/api/tasks/{task_id}/sync_calendar/', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                                'Authorization': 'Bearer ' + token
                            }},
                            body: JSON.stringify({{}})
                        }})
                        .then(response => {{
                            console.log('Статус ответа:', response.status);
                            if (!response.ok) {{
                                throw new Error('Ошибка HTTP: ' + response.status);
                            }}
                            return response.json().catch(e => {{
                                console.error('Ошибка парсинга JSON:', e);
                                throw new Error('Невозможно прочитать ответ от сервера');
                            }});
                        }})
                        .then(data => {{
                            console.log('Данные ответа:', data);
                            // Удаляем индикатор загрузки
                            document.getElementById('sync-loader').remove();

                            if (data.status === 'success') {{
                                alert(data.message);
                                if (data.event_link) {{
                                    if (confirm('Событие создано. Хотите открыть его в Google Calendar?')) {{
                                        window.open(data.event_link, '_blank');
                                    }}
                                }}
                            }} else {{
                                alert('Ошибка при синхронизации: ' + (data.message || 'Неизвестная ошибка'));
                            }}
                        }})
                        .catch(error => {{
                            // Удаляем индикатор загрузки
                            if (document.getElementById('sync-loader')) {{
                                document.getElementById('sync-loader').remove();
                            }}

                            console.error('Ошибка при синхронизации:', error);
                            alert('Ошибка при синхронизации с Google Calendar: ' + error.message);
                        }});
                    }}

                    // Выполняем синхронизацию с небольшой задержкой после загрузки страницы
                    document.addEventListener('DOMContentLoaded', function() {{
                        alert('Авторизация в Google Calendar успешно завершена! Сейчас задача будет синхронизирована.');
                        setTimeout(syncTask, 1000);
                    }});
                </script>
                """

                # Перенаправляем на страницу проекта
                logger.info(f"Отправляем HTML с JavaScript для автоматической синхронизации")
                return HttpResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <title>Синхронизация с Google Calendar</title>
                    <meta http-equiv="refresh" content="7; url=/projects/{project_id}/">
                    {sync_script}
                </head>
                <body>
                    <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
                        <h2>Авторизация в Google Calendar успешна!</h2>
                        <p>Выполняется синхронизация задачи...</p>
                        <p>Перенаправление на страницу проекта через 7 секунд...</p>
                    </div>
                </body>
                </html>
                """, content_type='text/html; charset=utf-8')
            except Task.DoesNotExist:
                logger.warning(f"Задача {task_id} не найдена в базе данных")
                # Если задача не найдена, перенаправляем на проекты
                return HttpResponse("""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <title>Задача не найдена</title>
                    <meta http-equiv="refresh" content="3; url=/projects/">
                    <style>
                        body { text-align: center; font-family: Arial, sans-serif; padding-top: 100px; }
                        .warning { color: orange; font-size: 24px; }
                        .redirect { margin-top: 20px; font-style: italic; }
                    </style>
                </head>
                <body>
                    <div class="warning">
                        ⚠️ Авторизация успешна, но задача не найдена
                    </div>
                    <div class="redirect">
                        Перенаправление на страницу проектов через 3 секунды...
                    </div>
                </body>
                </html>
                """, content_type='text/html; charset=utf-8')
        else:
            logger.warning(f"У пользователя {request.user.username} отсутствует токен Google Calendar")
            # Если пользователь не авторизован, показываем сообщение об ошибке
            return HttpResponse("""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Ошибка авторизации</title>
                <meta http-equiv="refresh" content="5; url=/projects/">
                <style>
                    body { text-align: center; font-family: Arial, sans-serif; padding-top: 100px; }
                    .error { color: red; font-size: 24px; }
                    .redirect { margin-top: 20px; font-style: italic; }
                </style>
            </head>
            <body>
                <div class="error">
                    ❌ Ошибка авторизации в Google Calendar
                </div>
                <div class="redirect">
                    Перенаправление на страницу проектов через 5 секунд...
                </div>
            </body>
            </html>
            """, content_type='text/html; charset=utf-8')


class GoogleCalendarStatusView(views.APIView):
    """
    Представление для проверки статуса подключения Google Calendar
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user_profile = request.user.profile
        is_connected = bool(user_profile.google_calendar_token)

        if is_connected:
            # Проверяем, не истек ли токен
            if user_profile.google_calendar_token_expiry:
                from django.utils import timezone
                is_expired = user_profile.google_calendar_token_expiry < timezone.now()
                is_connected = not is_expired

        return Response({
            'connected': is_connected,
            'expiry': user_profile.google_calendar_token_expiry.isoformat() if user_profile.google_calendar_token_expiry else None
        })