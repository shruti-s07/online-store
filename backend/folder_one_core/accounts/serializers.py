import re

from django.contrib.auth import password_validation
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from backend.shared.roles import Role
from config.loader import india

from .models import Address, Notification, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "role", "date_joined", "is_active"]
        read_only_fields = ["id", "email", "role", "date_joined", "is_active"]


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "role", "date_joined", "is_active", "last_login"]
        read_only_fields = ["id", "email", "date_joined", "last_login"]

    def validate_role(self, value):
        if value not in set(Role):
            raise serializers.ValidationError("Unknown role")
        return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name", "phone"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate(self, attrs):
        password_validation.validate_password(attrs["password"], User(email=attrs["email"]))
        return attrs

    def create(self, validated):
        # Self-registration always creates a Customer; only Admins can grant other roles.
        return User.objects.create_user(role=Role.CUSTOMER.value, **validated)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["old_password"]):
            raise serializers.ValidationError({"old_password": "Incorrect password"})
        password_validation.validate_password(attrs["new_password"], user)
        return attrs


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = ["id", "label", "full_name", "line1", "line2", "city", "state", "postal_code",
                  "country", "phone", "is_default"]

    def validate(self, attrs):
        """Addresses in the home country (config/india.yaml) need a valid PIN, state and mobile number."""
        places = india()
        country = attrs.get("country", getattr(self.instance, "country", ""))
        if (country or "").strip().lower() != places["country"].lower():
            return attrs
        errors = {}
        pin = str(attrs.get("postal_code", getattr(self.instance, "postal_code", ""))).replace(" ", "")
        if not re.fullmatch(places["pin_code_pattern"], pin):
            errors["postal_code"] = "Enter a valid 6-digit PIN code."
        else:
            attrs["postal_code"] = pin
        state = attrs.get("state", getattr(self.instance, "state", ""))
        if state and state not in places["states_and_union_territories"]:
            errors["state"] = "Choose a state or union territory from the list."
        phone = attrs.get("phone", getattr(self.instance, "phone", ""))
        if phone and not re.fullmatch(places["mobile_pattern"], phone.strip()):
            errors["phone"] = "Enter a valid 10-digit mobile number."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "payload", "status", "created_at", "read_at"]
