from django.db.models import Count
from rest_framework.response import Response
from rest_framework.views import APIView

from ai.common import load_meta
from backend.folder_one_core.orders.models import Order
from backend.shared.permissions import IsBackOffice
from config.loader import business


class RiskOverviewView(APIView):
    permission_classes = [IsBackOffice]

    def get(self, request):
        cfg = business()["risk"]
        levels = dict(Order.objects.exclude(risk_level="").values_list("risk_level").annotate(n=Count("id")))
        held = Order.objects.filter(status="ON_HOLD").order_by("-risk_score")[:50]
        meta = load_meta("fraud")
        return Response({
            "thresholds": {"medium": cfg["medium_threshold"], "high": cfg["high_threshold"]},
            "by_level": levels,
            "on_hold": [{"id": o.id, "risk_score": o.risk_score, "reasons": o.risk_reasons, "total": str(o.total),
                         "customer": o.user.email, "created_at": o.created_at} for o in held.select_related("user")],
            "model": meta and {"trained_at": meta["trained_at"], "metrics": meta["metrics"]},
        })
