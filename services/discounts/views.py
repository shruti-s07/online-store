from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from backend.folder_one_core.catalog.models import Product
from backend.shared.errors import DomainError
from backend.shared.permissions import IsAdmin

from . import suggest
from .models import DiscountRule, PastPromotion
from .serializers import DecisionSerializer, DiscountRuleSerializer, PastPromotionSerializer


class DiscountRuleViewSet(viewsets.ModelViewSet):
    """Admins manage discount rules. New manual rules start as DRAFT and must be approved."""

    serializer_class = DiscountRuleSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = DiscountRule.objects.all()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("source"):
            qs = qs.filter(source=p["source"])
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, status=DiscountRule.Status.DRAFT)

    def _decide(self, request, pk, status):
        rule = self.get_object()
        if rule.status != DiscountRule.Status.DRAFT:
            raise DomainError(f"Rule is already {rule.status}.", code="already_decided", status_code=409)
        if status == DiscountRule.Status.APPROVED and rule.action.get("type") == "percent":
            # Re-check the margin floor at approval time (prices/costs may have changed).
            for pid in rule.conditions.get("product_ids", []):
                p = Product.objects.filter(id=pid).first()
                if p and rule.action["value"] / 100 > suggest.max_discount_for_margin(p.price, p.cost) + 1e-9:
                    raise DomainError(f"Discount would push {p.name} below the minimum margin.",
                                      code="below_min_margin")
        ser = DecisionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        rule.status, rule.decided_by, rule.decided_at = status, request.user, timezone.now()
        if ser.validated_data.get("note"):
            rule.rationale = {**rule.rationale, "decision_note": ser.validated_data["note"]}
        rule.save()
        return Response(DiscountRuleSerializer(rule).data)

    @extend_schema(request=DecisionSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, pk, DiscountRule.Status.APPROVED)

    @extend_schema(request=DecisionSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, pk, DiscountRule.Status.REJECTED)

    @action(detail=False, methods=["get"])
    def slow_movers(self, request):
        return Response(suggest.analyse_slow_movers())

    @extend_schema(request=None)
    @action(detail=False, methods=["post"])
    def suggest(self, request):
        created = suggest.create_drafts(request.user)
        return Response(DiscountRuleSerializer(created, many=True).data, status=201)


class PastPromotionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PastPromotionSerializer
    permission_classes = [IsAdmin]
    queryset = PastPromotion.objects.select_related("category")

    @action(detail=False, methods=["get"])
    def elasticity(self, request):
        from backend.folder_one_core.catalog.models import Category
        return Response([{"category": c.name, **suggest.estimate_elasticity(c)} for c in Category.objects.all()])
