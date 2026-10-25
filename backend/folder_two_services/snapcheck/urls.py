from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("snapchecks", views.SnapCheckViewSet, basename="snapcheck")
urlpatterns = [
    path("search/photo/", views.PhotoSearchView.as_view(), name="photo-search"),
    path("snapcheck/status/", views.SnapCheckStatusView.as_view(), name="snapcheck-status"),
    *router.urls,
]
