from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("addresses", views.AddressViewSet, basename="address")
router.register("notifications", views.NotificationViewSet, basename="notification")
router.register("admin/users", views.AdminUserViewSet, basename="admin-user")

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="token-refresh"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("auth/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    *router.urls,
]
