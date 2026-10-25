from django.urls import path

from . import views

urlpatterns = [
    path("forecasting/products/<int:product_id>/", views.ForecastView.as_view(), name="forecast-product"),
    path("forecasting/restock/", views.RestockView.as_view(), name="restock"),
    path("forecasting/summary/", views.ForecastSummaryView.as_view(), name="forecast-summary"),
]
