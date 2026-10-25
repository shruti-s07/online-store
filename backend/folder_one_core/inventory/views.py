from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from backend.folder_one_core.catalog.models import Product
from backend.shared.permissions import IsBackOffice
from config.loader import business

from .models import StockMovement
from .services import adjust_stock, availability_map


class AdjustSerializer(serializers.Serializer):
    delta = serializers.IntegerField()
    reason = serializers.ChoiceField(choices=[r for r in StockMovement.Reason.values if r != "SALE"])
    reference = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_delta(self, v):
        if v == 0:
            raise serializers.ValidationError("Delta must not be zero.")
        return v


class MovementSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", default=None, read_only=True)

    class Meta:
        model = StockMovement
        fields = ["id", "delta", "reason", "reference", "user_email", "created_at"]


class InventoryViewSet(viewsets.ViewSet):
    permission_classes = [IsBackOffice]

    def list(self, request):
        products = Product.objects.select_related("category").order_by("name")
        if request.query_params.get("search"):
            products = products.filter(name__icontains=request.query_params["search"])
        avail = availability_map([p.id for p in products])
        threshold = business()["inventory"]["low_stock_threshold"]
        rows = [{"product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category.name, **avail[p.id],
                 "low_stock": avail[p.id]["available"] <= threshold} for p in products]
        if request.query_params.get("low_stock") == "true":
            rows = [r for r in rows if r["low_stock"]]
        return Response(rows)

    @extend_schema(request=AdjustSerializer)
    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        product = Product.objects.get(pk=pk)
        ser = AdjustSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        adjust_stock(product, ser.validated_data["delta"], ser.validated_data["reason"], request.user,
                     ser.validated_data.get("reference", ""))
        return Response(availability_map([product.id])[product.id])

    @action(detail=True, methods=["get"])
    def movements(self, request, pk=None):
        qs = StockMovement.objects.filter(product_id=pk).select_related("user")[: business()["api"]["max_page_size"]]
        return Response(MovementSerializer(qs, many=True).data)
