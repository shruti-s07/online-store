from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("orders", views.OrderViewSet, basename="order")
urlpatterns = [
    path("checkout/reserve/", views.ReserveView.as_view(), name="checkout-reserve"),
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    *router.urls,
]
