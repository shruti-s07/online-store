from decimal import Decimal

from rest_framework import serializers

from backend.folder_one_core.inventory.services import availability_map

from .models import Category, Product, ProductImage


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "is_primary", "alt_text"]


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    available = serializers.SerializerMethodField()
    on_hand = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    rating_avg = serializers.FloatField(read_only=True, required=False, allow_null=True)
    rating_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Product
        fields = ["id", "sku", "name", "description", "brand", "category", "category_name", "price", "cost",
                  "supplier_lead_time_days", "attributes", "images", "available", "on_hand", "in_stock",
                  "is_deleted", "created_at", "updated_at", "rating_avg", "rating_count"]
        read_only_fields = ["is_deleted", "created_at", "updated_at"]

    def _avail(self, obj):
        cache = self.context.setdefault("_availability", {})
        if obj.id not in cache:
            cache.update(availability_map([obj.id]))
        return cache.get(obj.id, {"available": 0, "on_hand": 0})

    def get_available(self, obj):
        return self._avail(obj)["available"]

    def get_on_hand(self, obj):
        return self._avail(obj)["on_hand"]

    def get_in_stock(self, obj):
        return self._avail(obj)["available"] > 0

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get("request")
        # Cost/margin data is for the back office only.
        from backend.shared.permissions import is_back_office
        if not (request and is_back_office(request.user)):
            data.pop("cost", None)
            data.pop("on_hand", None)
        return data

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be positive.")
        return value

    def validate_cost(self, value):
        if value < 0:
            raise serializers.ValidationError("Cost cannot be negative.")
        return value

    def validate(self, attrs):
        price = attrs.get("price", getattr(self.instance, "price", None))
        cost = attrs.get("cost", getattr(self.instance, "cost", None))
        if price is not None and cost is not None and Decimal(cost) > Decimal(price):
            raise serializers.ValidationError({"cost": "Cost must not exceed price."})
        return attrs
