from django.urls import path

from . import views

urlpatterns = [path("risk/overview/", views.RiskOverviewView.as_view(), name="risk-overview")]
