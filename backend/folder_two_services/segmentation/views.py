from django.db.models import Avg, Count
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.common import load_meta
from backend.shared.permissions import IsBackOffice

from . import service
from .models import CustomerSegment


class SegmentRowSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source="user.email")

    class Meta:
        model = CustomerSegment
        fields = ["user", "email", "segment", "recency_days", "frequency", "monetary", "tenure_days", "computed_at"]


class SegmentSummaryView(APIView):
    permission_classes = [IsBackOffice]

    def get(self, request):
        rows = (CustomerSegment.objects.values("segment")
                .annotate(customers=Count("id"), recency_days=Avg("recency_days"), frequency=Avg("frequency"),
                          monetary=Avg("monetary"), tenure_days=Avg("tenure_days")).order_by("segment"))
        meta = load_meta("segmentation") or {}
        return Response({"segments": [{k: (round(float(v), 2) if isinstance(v, float) or k == "monetary" else v)
                                       for k, v in r.items()} for r in rows],
                         "customers_without_orders": service.customers_without_orders(),
                         "model": {"trained_at": meta.get("trained_at"), "metrics": meta.get("metrics")}})


class SegmentCustomersView(ListAPIView):
    permission_classes = [IsBackOffice]
    serializer_class = SegmentRowSerializer

    def get_queryset(self):
        qs = CustomerSegment.objects.select_related("user").order_by("-monetary")
        if self.request.query_params.get("segment"):
            qs = qs.filter(segment=self.request.query_params["segment"])
        return qs
