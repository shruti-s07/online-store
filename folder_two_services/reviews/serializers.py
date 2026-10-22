from rest_framework import serializers

from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "product", "product_name", "author", "rating", "title", "body", "status", "verified_purchase",
                  "sentiment", "sentiment_score", "fake_score", "fake_reasons", "created_at"]
        read_only_fields = ["product", "status", "verified_purchase", "sentiment", "sentiment_score", "fake_score",
                            "fake_reasons", "created_at"]

    def get_author(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name[:1]}.".strip() if obj.user.first_name else "Customer"

    def validate_rating(self, v):
        if not 1 <= v <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return v

    def to_representation(self, obj):
        data = super().to_representation(obj)
        req = self.context.get("request")
        from backend.shared.permissions import is_back_office
        if not (req and is_back_office(req.user)):
            for k in ("fake_score", "fake_reasons", "status"):
                data.pop(k, None)
        return data


class ModerateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Review.Status.values)
