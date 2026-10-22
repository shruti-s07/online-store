from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.folder_one_core.catalog.models import Product
from backend.folder_one_core.orders.models import OrderItem
from backend.shared.errors import DomainError
from backend.shared.permissions import IsAnyRole, IsBackOffice, IsCustomer

from . import intelligence
from .models import Review
from .serializers import ModerateSerializer, ReviewSerializer


class ProductReviewsView(APIView):
    def get_permissions(self):
        return [IsCustomer()] if self.request.method == "POST" else [IsAnyRole()]

    def get(self, request, product_id: int):
        qs = Review.objects.filter(product_id=product_id, status=Review.Status.VISIBLE).select_related("user", "product")
        from backend.shared.pagination import ConfigPagination
        pager = ConfigPagination()
        page = pager.paginate_queryset(qs, request, view=self)
        return pager.get_paginated_response(ReviewSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(request=ReviewSerializer, responses=ReviewSerializer)
    def post(self, request, product_id: int):
        product = Product.objects.filter(id=product_id).first()
        if not product:
            raise DomainError("Product not found.", code="not_found", status_code=404)
        ser = ReviewSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        item = (OrderItem.objects.filter(order__user=request.user, product=product, order__status="DELIVERED")
                .order_by("-order__created_at").first())
        try:
            with transaction.atomic():
                review = ser.save(user=request.user, product=product, order_item=item, verified_purchase=item is not None)
        except IntegrityError:
            raise DomainError("You have already reviewed this product.", code="duplicate_review", status_code=409)
        intelligence.analyse_product(product.id)
        review.refresh_from_db()
        return Response(ReviewSerializer(review, context={"request": request}).data, status=201)


class ReviewInsightsView(APIView):
    permission_classes = [IsAnyRole]

    def get(self, request, product_id: int):
        product = Product.objects.select_related("category").filter(id=product_id).first()
        if not product:
            raise DomainError("Product not found.", code="not_found", status_code=404)
        return Response(intelligence.summary(product))


class ModerationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [IsBackOffice]

    def get_queryset(self):
        qs = Review.objects.select_related("user", "product")
        status = self.request.query_params.get("status", Review.Status.FLAGGED)
        if status != "ALL":
            qs = qs.filter(status=status)
        return qs.order_by("-fake_score", "-created_at")

    @extend_schema(request=ModerateSerializer)
    @action(detail=True, methods=["post"])
    def moderate(self, request, pk=None):
        ser = ModerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        review = Review.objects.get(pk=pk)
        review.status = ser.validated_data["status"]
        review.moderated_by, review.moderated_at = request.user, timezone.now()
        review.save(update_fields=["status", "moderated_by", "moderated_at"])
        return Response(ReviewSerializer(review, context={"request": request}).data)
