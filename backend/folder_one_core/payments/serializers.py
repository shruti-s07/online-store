from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "method", "amount", "status", "gateway_ref", "error_code", "message", "created_at", "refunded_at"]
