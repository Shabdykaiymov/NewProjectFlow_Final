from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from .models import UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    """Профиль юзера"""

    class Meta:
        model = UserProfile
        fields = ['id', 'google_calendar_token_expiry']
        read_only_fields = ['id']


class UserSerializer(serializers.ModelSerializer):
    """Инфа о юзере"""
    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'date_joined', 'profile']
        read_only_fields = ['id', 'date_joined']


class RegisterSerializer(serializers.ModelSerializer):
    """Регистрация"""
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password]
    )
    password2 = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2', 'first_name', 'last_name']

    def validate(self, attrs):
        # проверяем что пароли одинаковые
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Пароли не совпадают"})

        # проверка уникальности email
        if User.objects.filter(email=attrs['email']).exists():
            raise serializers.ValidationError({"email": "Пользователь с таким email уже существует"})

        return attrs

    def create(self, validated_data):
        # Удаление password2 из validated_data
        validated_data.pop('password2')

        # Создание юзера
        user = User.objects.create(
            username=validated_data['username'],
            email=validated_data['email'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )

        # хешируем пароль через джанго
        user.set_password(validated_data['password'])
        user.save()

        return user