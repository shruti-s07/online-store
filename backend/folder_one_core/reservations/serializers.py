from rest_framework import serializers

from .models import Reservation, ReservationItem


class ReservationItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = ReservationItem
        fields = ["product", "product_name", "quantity"]


class ReservationSerializer(serializers.ModelSerializer):
    items = ReservationItemSerializer(many=True, read_only=True)
    seconds_left = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = ["id", "status", "expires_at", "created_at", "seconds_left", "items"]

    def get_seconds_left(self, obj):
        from django.utils import timezone
        if obj.status != Reservation.Status.ACTIVE:
            return 0
        return max(0, int((obj.expires_at - timezone.now()).total_seconds()))
