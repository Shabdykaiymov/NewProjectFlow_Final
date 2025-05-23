from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import RegisterView, CustomTokenObtainPairView, UserInfoView, LogoutView,UserStatisticsView,ProfileUpdateView

urlpatterns = [
    # Регистрация нового юзера
    path('register/', RegisterView.as_view(), name='register'),

    # Получение JWT токенов
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Выход из системы (добавление токена в черный список)
    path('logout/', LogoutView.as_view(), name='logout'),

    # Информация о текущем юзере
    path('me/', UserInfoView.as_view(), name='user_info'),

    # URL для получения статистики юзера
    path('statistics/', UserStatisticsView.as_view(), name='user_statistics'),

    # URL для Update профиля юзера
    path('profile/update/', ProfileUpdateView.as_view(), name='profile_update'),
]