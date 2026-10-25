from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from backend.shared.permissions import IsAdmin, IsAnyRole
from backend.shared.roles import Role

from .models import Address, Notification, User
from .serializers import (AddressSerializer, AdminUserSerializer, ChangePasswordSerializer,
                          LoginSerializer, NotificationSerializer, RegisterSerializer, UserSerializer)
from .throttles import LoginThrottle, RegisterThrottle


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = [RegisterThrottle]

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = [LoginThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            User.objects.filter(email__iexact=request.data.get("email", "")).update(last_login=timezone.now())
        return response


class RefreshView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAnyRole]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    permission_classes = [IsAnyRole]

    @extend_schema(request=ChangePasswordSerializer, responses={204: None})
    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        request.user.set_password(ser.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [IsAnyRole]
    pagination_class = None

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        has_any = Address.objects.filter(user=self.request.user).exists()
        is_default = serializer.validated_data.get("is_default") or not has_any
        if is_default:
            Address.objects.filter(user=self.request.user).update(is_default=False)
        serializer.save(user=self.request.user, is_default=is_default)

    @transaction.atomic
    def perform_update(self, serializer):
        if serializer.validated_data.get("is_default"):
            Address.objects.filter(user=self.request.user).update(is_default=False)
        serializer.save()


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAnyRole]

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get("unread") == "true":
            qs = qs.exclude(status=Notification.Status.READ)
        return qs

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        n = self.get_queryset().get(pk=pk)
        n.status, n.read_at = Notification.Status.READ, timezone.now()
        n.save(update_fields=["status", "read_at"])
        return Response(NotificationSerializer(n).data)


class AdminUserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                       viewsets.GenericViewSet):
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdmin]
    queryset = User.objects.all().order_by("id")

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("role"):
            qs = qs.filter(role=p["role"])
        if p.get("search"):
            qs = qs.filter(email__icontains=p["search"])
        return qs

    def perform_update(self, serializer):
        target = serializer.instance
        if target == self.request.user and (
            serializer.validated_data.get("role", target.role) != Role.ADMIN
            or serializer.validated_data.get("is_active", True) is False
        ):
            from backend.shared.errors import DomainError
            raise DomainError("You cannot demote or deactivate yourself.", code="self_lockout")
        serializer.save()

    @action(detail=False, methods=["get"])
    def roles(self, request):
        return Response([r.value for r in Role])
