from rest_framework import serializers

from backend.folder_one_core.payments.serializers import PaymentSerializer
from backend.shared.order_states import allowed_targets
from backend.shared.roles import Role

from .models import Order, OrderItem, OrderStatusHistory


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["id", "product", "sku", "name", "unit_price", "quantity", "line_total"]


class HistorySerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", default=None, read_only=True)

    class Meta:
        model = OrderStatusHistory
        fields = ["from_status", "to_status", "actor_label", "actor_email", "note", "created_at"]


class OrderListSerializer(serializers.ModelSerializer):
    customer_email = serializers.CharField(source="user.email", read_only=True)
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "status", "payment_method", "total", "risk_score", "risk_level", "customer_email",
                  "item_count", "created_at", "updated_at"]


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    history = HistorySerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    customer_email = serializers.CharField(source="user.email", read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["id", "status", "payment_method", "subtotal", "discount_total", "total", "discount_code",
                  "discounts", "shipping_address", "billing_address", "address_match", "risk_score", "risk_level",
                  "risk_reasons", "risk_model", "fraud_confirmed", "cancel_reason", "return_reason", "customer_email",
                  "items", "history", "payments", "allowed_transitions", "created_at", "updated_at"]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get("request")
        if request and request.user.role == Role.CUSTOMER:
            for k in ("risk_score", "risk_level", "risk_reasons", "risk_model", "fraud_confirmed"):
                data.pop(k, None)
        return data

    def get_allowed_transitions(self, obj):
        request = self.context.get("request")
        return allowed_targets(obj.status, Role(request.user.role)) if request else []


class CheckoutSerializer(serializers.Serializer):
    shipping_address_id = serializers.IntegerField()
    billing_address_id = serializers.IntegerField(required=False, allow_null=True)
    payment_method = serializers.CharField()
    payment_token = serializers.CharField(required=False, allow_blank=True)


class PaySerializer(serializers.Serializer):
    payment_method = serializers.CharField()
    payment_token = serializers.CharField()


class OtpSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=12)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)


class TransitionSerializer(serializers.Serializer):
    status = serializers.CharField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    fraud_confirmed = serializers.BooleanField(required=False)
