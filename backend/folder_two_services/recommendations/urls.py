from django.urls import path

from . import views

urlpatterns = [
    path("recommendations/", views.MyRecommendationsView.as_view(), name="recommendations"),
    path("products/<int:product_id>/similar/", views.SimilarProductsView.as_view(), name="similar-products"),
]
