from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("discounts/rules", views.DiscountRuleViewSet, basename="discount-rule")
router.register("discounts/promotions", views.PastPromotionViewSet, basename="past-promotion")
urlpatterns = router.urls
