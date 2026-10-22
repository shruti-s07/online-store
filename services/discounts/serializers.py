from rest_framework import serializers

from .engine import times_used, validate_rule_data
from .models import DiscountRule, PastPromotion


class DiscountRuleSerializer(serializers.ModelSerializer):
    times_used = serializers.SerializerMethodField()

    class Meta:
        model = DiscountRule
        fields = ["id", "name", "code", "conditions", "action", "status", "source", "priority", "stackable",
                  "starts_at", "ends_at", "max_uses", "times_used", "rationale", "created_at", "decided_at"]
        read_only_fields = ["status", "source", "rationale", "created_at", "decided_at"]

    def get_times_used(self, obj):
        return times_used(obj.id)

    def validate_code(self, v):
        return v.strip().upper() or None if v else None

    def validate(self, attrs):
        conditions = attrs.get("conditions", getattr(self.instance, "conditions", {}))
        action = attrs.get("action", getattr(self.instance, "action", None))
        errors = validate_rule_data(conditions, action)
        if errors:
            raise serializers.ValidationError({"rule": errors})
        return attrs


class PastPromotionSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", default=None)

    class Meta:
        model = PastPromotion
        fields = ["id", "name", "category", "category_name", "product", "discount_pct", "starts_on", "ends_on"]


class DecisionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)
