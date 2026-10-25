from django.urls import path

from . import views

urlpatterns = [
    path("cart/", views.CartView.as_view(), name="cart"),
    path("cart/items/", views.CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<int:product_id>/", views.CartItemView.as_view(), name="cart-item"),
    path("cart/discount-code/", views.DiscountCodeView.as_view(), name="cart-discount-code"),
]
