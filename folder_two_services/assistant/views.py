from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.shared.permissions import IsAnyRole, IsBackOffice, IsCustomer

from . import engine
from .models import ChatMessage


class MessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=1000)


class ChatView(APIView):
    permission_classes = [IsCustomer]
    channel = "assistant"

    @extend_schema(request=MessageSerializer)
    def post(self, request):
        ser = MessageSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(engine.handle(request.user, self.channel, ser.validated_data["message"]))


class AnalyticsView(ChatView):
    permission_classes = [IsBackOffice]
    channel = "analytics"


class ConfirmActionView(APIView):
    permission_classes = [IsAnyRole]

    @extend_schema(request=None)
    def post(self, request, action_id: int):
        return Response(engine.confirm(request.user, action_id))


class CancelActionView(APIView):
    permission_classes = [IsAnyRole]

    @extend_schema(request=None)
    def post(self, request, action_id: int):
        return Response(engine.cancel(request.user, action_id))


class HistoryView(APIView):
    permission_classes = [IsAnyRole]

    def get(self, request):
        channel = request.query_params.get("channel", "assistant")
        rows = ChatMessage.objects.filter(user=request.user, channel=channel).order_by("-created_at")[:50]
        return Response([{"role": m.role, "content": m.content, "meta": m.meta, "created_at": m.created_at}
                         for m in reversed(list(rows))])


class StatusView(APIView):
    permission_classes = [IsAnyRole]

    def get(self, request):
        from ai.common import load_meta
        meta = load_meta("intents") or {}
        return Response({"engine": engine.engine_name(), "llm_enabled": engine.llm_enabled(),
                         "intent_model": {"trained_at": meta.get("trained_at"), "metrics": meta.get("metrics")}})
