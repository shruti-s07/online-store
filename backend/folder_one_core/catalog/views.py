from django.db import transaction
from django.db.models import Avg, Count, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from backend.folder_one_core.inventory.services import availability_map, ensure_inventory
from backend.shared.permissions import ReadAnyWriteBackOffice, is_back_office

from .models import Category, Product, ProductImage
from .serializers import CategorySerializer, ProductImageSerializer, ProductSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [ReadAnyWriteBackOffice]
    queryset = Category.objects.all()
    pagination_class = None


SORTS = {"name": "name", "-name": "-name", "price": "price", "-price": "-price",
         "newest": "-created_at", "rating": "-rating_avg"}


class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [ReadAnyWriteBackOffice]

    def get_queryset(self):
        p = self.request.query_params
        include_deleted = p.get("include_deleted") == "true" and is_back_office(self.request.user)
        qs = (Product.all_objects if include_deleted else Product.objects).select_related("category")
        qs = qs.prefetch_related("images").annotate(
            rating_avg=Avg("reviews__rating", filter=Q(reviews__status="VISIBLE")),
            rating_count=Count("reviews", filter=Q(reviews__status="VISIBLE")),
        )
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(Q(name__icontains=s) | Q(description__icontains=s) | Q(sku__iexact=s) | Q(brand__icontains=s))
        if p.get("category"):
            qs = qs.filter(Q(category__slug=p["category"]) | Q(category__id__in=[c for c in [p["category"]] if c.isdigit()]))
        if p.get("brand"):
            qs = qs.filter(brand__iexact=p["brand"])
        if p.get("min_price"):
            qs = qs.filter(price__gte=p["min_price"])
        if p.get("max_price"):
            qs = qs.filter(price__lte=p["max_price"])
        qs = qs.order_by(SORTS.get(p.get("sort", "name"), "name"), "id")
        if p.get("in_stock") == "true":
            ids = list(qs.values_list("id", flat=True))
            avail = availability_map(ids)
            qs = qs.filter(id__in=[i for i in ids if avail.get(i, {}).get("available", 0) > 0])
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["_availability"] = {}
        return ctx

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        ctx = self.get_serializer_context()
        ctx["_availability"].update(availability_map([p.id for p in page]))
        return self.get_paginated_response(ProductSerializer(page, many=True, context=ctx).data)

    @transaction.atomic
    def perform_create(self, serializer):
        product = serializer.save()
        ensure_inventory(product)

    def destroy(self, request, *args, **kwargs):
        product = self.get_object()
        product.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        product = Product.all_objects.get(pk=pk)
        product.restore()
        return Response(ProductSerializer(product, context=self.get_serializer_context()).data)

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {
        "image": {"type": "string", "format": "binary"}, "is_primary": {"type": "boolean"}}}},
        responses=ProductImageSerializer)
    @action(detail=True, methods=["post"], parser_classes=[parsers.MultiPartParser])
    def images(self, request, pk=None):
        product = self.get_object()
        upload = request.FILES.get("image")
        if not upload:
            return Response({"detail": "image file is required", "code": "invalid"}, status=400)
        from PIL import Image
        try:
            Image.open(upload).verify()
            upload.seek(0)
        except Exception:
            return Response({"detail": "File is not a valid image", "code": "invalid_image"}, status=400)
        primary = str(request.data.get("is_primary", "")).lower() in {"1", "true"} or not product.images.exists()
        if primary:
            product.images.update(is_primary=False)
        img = ProductImage.objects.create(product=product, image=upload, is_primary=primary, alt_text=product.name)
        return Response(ProductImageSerializer(img, context={"request": request}).data, status=201)

    @extend_schema(parameters=[OpenApiParameter("image_id", int)])
    @action(detail=True, methods=["delete"], url_path=r"images/(?P<image_id>\d+)")
    def delete_image(self, request, pk=None, image_id=None):
        self.get_object().images.filter(id=image_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def brands(self, request):
        return Response(sorted(set(Product.objects.exclude(brand="").values_list("brand", flat=True))))
