from django.urls import path

from . import views

urlpatterns = [
    path("assistant/chat/", views.ChatView.as_view(), name="assistant-chat"),
    path("assistant/analytics/", views.AnalyticsView.as_view(), name="assistant-analytics"),
    path("assistant/actions/<int:action_id>/confirm/", views.ConfirmActionView.as_view(), name="assistant-confirm"),
    path("assistant/actions/<int:action_id>/cancel/", views.CancelActionView.as_view(), name="assistant-cancel"),
    path("assistant/history/", views.HistoryView.as_view(), name="assistant-history"),
    path("assistant/status/", views.StatusView.as_view(), name="assistant-status"),
]
