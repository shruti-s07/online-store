from django.urls import path

from . import views

urlpatterns = [
    path("segments/summary/", views.SegmentSummaryView.as_view(), name="segments-summary"),
    path("segments/customers/", views.SegmentCustomersView.as_view(), name="segments-customers"),
]
