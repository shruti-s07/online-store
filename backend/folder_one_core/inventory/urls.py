from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("inventory", views.InventoryViewSet, basename="inventory")
urlpatterns = router.urls
