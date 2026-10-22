from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("reviews/moderation", views.ModerationViewSet, basename="review-moderation")
urlpatterns = [
    path("products/<int:product_id>/reviews/", views.ProductReviewsView.as_view(), name="product-reviews"),
    path("products/<int:product_id>/review-insights/", views.ReviewInsightsView.as_view(), name="review-insights"),
    *router.urls,
]
