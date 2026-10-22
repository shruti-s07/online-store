import io

from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from PIL import Image, UnidentifiedImageError
from rest_framework import mixins, parsers, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.folder_one_core.orders.models import OrderItem
from backend.shared.errors import DomainError
from backend.shared.permissions import IsAnyRole, IsBackOffice, IsCustomer, is_back_office

from . import service
from .models import SnapCheck

UPLOAD = {"multipart/form-data": {"type": "object", "properties": {
    "image": {"type": "string", "format": "binary"}, "order_item_id": {"type": "integer"},
    "note": {"type": "string"}}}}


def read_image(request) -> tuple[Image.Image, object]:
    f = request.FILES.get("image")
    if not f:
        raise DomainError("An image file is required.", code="invalid")
    try:
        img = Image.open(io.BytesIO(f.read())).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise DomainError("The file is not a valid image.", code="invalid_image")
    f.seek(0)
    return img, f


class SnapCheckSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source="order_item.order_id", read_only=True)
    product_name = serializers.CharField(source="order_item.name", read_only=True)
    product_id = serializers.IntegerField(source="order_item.product_id", read_only=True)
    customer_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = SnapCheck
        fields = ["id", "order_id", "product_id", "product_name", "customer_email", "similarity", "verdict", "method",
                  "fast_tracked", "status", "customer_note", "resolution", "created_at"]


class SnapCheckViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SnapCheckSerializer
    permission_classes = [IsAnyRole]

    def get_queryset(self):
        qs = SnapCheck.objects.select_related("order_item", "user")
        if not is_back_office(self.request.user):
            qs = qs.filter(user=self.request.user)
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @extend_schema(request=UPLOAD, responses=SnapCheckSerializer)
    def create(self, request):
        if not IsCustomer().has_permission(request, self):
            self.permission_denied(request)
        img, f = read_image(request)
        item = OrderItem.objects.select_related("order", "product").filter(
            id=request.data.get("order_item_id"), order__user=request.user).first()
        if not item:
            raise DomainError("Order item not found.", code="not_found", status_code=404)
        if item.order.status not in ("DELIVERED", "RETURN_REQUESTED"):
            raise DomainError("SnapCheck is available once the order is delivered.", code="not_delivered",
                              status_code=409)
        result = service.compare(img, item.product)
        check = SnapCheck.objects.create(
            user=request.user, order_item=item, image=f, similarity=result["similarity"] or 0.0,
            verdict=result["verdict"], method=result["method"], fast_tracked=result["verdict"] == "MISMATCH",
            customer_note=request.data.get("note", "")[:300])
        if check.fast_tracked:
            service.fast_track(check)
        data = SnapCheckSerializer(check).data
        data["thresholds"] = result.get("thresholds")
        return Response(data, status=201)

    create.parser_classes = [parsers.MultiPartParser]

    def get_parsers(self):
        return [parsers.MultiPartParser(), parsers.JSONParser()]

    @action(detail=True, methods=["get"])
    def image(self, request, pk=None):
        check = self.get_queryset().get(pk=pk)
        return FileResponse(check.image.open("rb"), content_type="image/png")

    @extend_schema(request={"application/json": {"type": "object", "properties": {"resolution": {"type": "string"}}}})
    @action(detail=True, methods=["post"], permission_classes=[IsBackOffice])
    def resolve(self, request, pk=None):
        check = SnapCheck.objects.get(pk=pk)
        check.status, check.resolution, check.resolved_by = SnapCheck.Status.RESOLVED, \
            str(request.data.get("resolution", ""))[:300], request.user
        check.save(update_fields=["status", "resolution", "resolved_by"])
        return Response(SnapCheckSerializer(check).data)


class PhotoSearchView(APIView):
    permission_classes = [IsAnyRole]
    parser_classes = [parsers.MultiPartParser]

    @extend_schema(request=UPLOAD)
    def post(self, request):
        img, _ = read_image(request)
        return Response(service.search_by_photo(img))


class SnapCheckStatusView(APIView):
    permission_classes = [IsAnyRole]

    def get(self, request):
        from ai.embedding import get_embedder
        emb = get_embedder()
        return Response({"method": emb.name, "is_clip": emb.is_clip, "thresholds": service.thresholds(),
                         "checked_at": timezone.now()})
