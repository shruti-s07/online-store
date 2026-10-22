from django.urls import path

from . import views

urlpatterns = [
    path("jobs/runs/", views.JobRunListView.as_view(), name="job-runs"),
    path("jobs/<str:name>/run/", views.TriggerJobView.as_view(), name="job-run"),
    path("ai/models/", views.ModelCatalogView.as_view(), name="ai-models"),
]
