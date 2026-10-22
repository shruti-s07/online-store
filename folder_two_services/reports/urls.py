from django.urls import path

from . import views

urlpatterns = [
    path("reports/", views.ReportListView.as_view(), name="reports"),
    path("reports/my-orders/", views.MyOrderHistoryView.as_view(), name="report-my-orders"),
    path("reports/<str:name>/", views.ReportView.as_view(), name="report"),
]
