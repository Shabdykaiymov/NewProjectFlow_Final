from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.db.models import Count, Q
from projects.models import Project
from tasks.models import Task
from .serializers import UserSerializer, RegisterSerializer

class RegisterView(generics.CreateAPIView):
    """
    Представление для регистрации новых пользователей
    """
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Генерируем JWT токены для нового пользователя
        refresh = RefreshToken.for_user(user)

        response_data = {
            "user": UserSerializer(user).data,
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }
        }

        return Response(response_data, status=status.HTTP_201_CREATED)


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Кастомное представление для получения JWT токенов
    с дополнительной информацией о пользователе
    """

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)

            # Если аутентификация успешна, добавляем информацию о пользователе
            if response.status_code == 200:
                user = User.objects.get(username=request.data.get('username'))
                response.data['user'] = UserSerializer(user).data

            return response
        except:
            # Сообщение об ошибке для неверного логина/пароля
            return Response(
                {"detail": "Проверьте логин или пароль"},
                status=status.HTTP_400_BAD_REQUEST
            )

class UserInfoView(APIView):
    """
    Представление для получения информации о текущем пользователе
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = UserSerializer(user)
        return Response(serializer.data)


class LogoutView(APIView):
    """
    Представление для выхода из системы (добавление токена в черный список)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            # Получаем refresh токен из запроса
            refresh_token = request.data.get('refresh')

            if not refresh_token:
                return Response({"error": "Refresh token is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Инвалидируем токен (добавляем в черный список)
            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response({"success": "Logout successful"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class UserStatisticsView(APIView):
        """
        Представление для получения статистики пользователя
        """
        permission_classes = [permissions.IsAuthenticated]

        def get(self, request):
            user = request.user

            # Количество проектов пользователя
            projects_count = Project.objects.filter(members=user).count()

            # Количество задач, где пользователь является исполнителем
            tasks_count = Task.objects.filter(assignee=user).count()

            # Количество завершенных задач пользователя
            completed_tasks_count = Task.objects.filter(
                assignee=user,
                status='Завершена'
            ).count()

            return Response({
                'projects_count': projects_count,
                'tasks_count': tasks_count,
                'completed_tasks_count': completed_tasks_count
            })

class ProfileUpdateView(APIView):
    """
    Представление для обновления профиля пользователя
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')

        #  Обновление имени и фамилии
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name

        # Обновление пароля если введены все необходимые поля
        if current_password and new_password:
            if not user.check_password(current_password):
                return Response({"detail": "Неверный текущий пароль"}, status=status.HTTP_400_BAD_REQUEST)
            user.set_password(new_password)

        # Сохраняем изменения
        user.save()

        return Response({"detail": "Профиль успешно обновлен"})