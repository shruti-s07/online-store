from django.db.models import Count, Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.folder_one_core.payments.serializers import PaymentSerializer
from backend.folder_one_core.payments.services import pay
from backend.folder_one_core.reservations.serializers import ReservationSerializer
from backend.folder_one_core.reservations.services import latest_reservation
from backend.shared.errors import DomainError
from backend.shared.order_states import OrderStatus
from backend.shared.permissions import IsAnyRole, IsBackOffice, IsCustomer, is_back_office
from backend.shared.roles import Role

from . import services
from .models import Order
from .serializers import (CheckoutSerializer, OrderDetailSerializer, OrderListSerializer, OtpSerializer,
                          PaySerializer, ReasonSerializer, TransitionSerializer)

IDEMPOTENCY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _idem(request) -> str:
    return request.headers.get("Idempotency-Key", "").strip()


class ReserveView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=None, responses=ReservationSerializer)
    def post(self, request):
        res = services.reserve_cart(request.user)
        return Response(ReservationSerializer(res).data, status=201)

    @extend_schema(responses=ReservationSerializer)
    def get(self, request):
        res = latest_reservation(request.user)
        if not res:
            return Response({"status": None, "detail": "No reservation"})
        data = ReservationSerializer(res).data
        if res.status == res.Status.EXPIRED:
            data["detail"] = "Your reservation expired. Items were released back to stock."
        return Response(data)


class CheckoutView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=CheckoutSerializer, parameters=[IDEMPOTENCY], responses=OrderDetailSerializer)
    def post(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        order, info = services.checkout(
            request.user, shipping_address_id=v["shipping_address_id"],
            billing_address_id=v.get("billing_address_id"), payment_method=v["payment_method"],
            payment_token=v.get("payment_token") or None, idempotency_key=_idem(request))
        data = OrderDetailSerializer(order, context={"request": request}).data
        data.update(info)
        return Response(data, status=200 if info.get("replayed") else 201)


class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAnyRole]

    def get_serializer_class(self):
        return OrderListSerializer if self.action == "list" else OrderDetailSerializer

    def get_queryset(self):
        qs = Order.objects.select_related("user")
        if not is_back_office(self.request.user):
            qs = qs.filter(user=self.request.user)
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("risk_level") and is_back_office(self.request.user):
            qs = qs.filter(risk_level=p["risk_level"])
        if p.get("search") and is_back_office(self.request.user):
            s = p["search"]
            qs = qs.filter(id=int(s)) if s.isdigit() else qs.filter(user__email__icontains=s)
        if self.action == "list":
            qs = qs.annotate(item_count=Sum("items__quantity")).order_by("-created_at", "-id")
        else:
            qs = qs.prefetch_related("items", "history__actor", "payments")
        return qs

    @extend_schema(request=PaySerializer, parameters=[IDEMPOTENCY], responses=PaymentSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsCustomer])
    def pay(self, request, pk=None):
        ser = PaySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payment = pay(int(pk), request.user, _idem(request), ser.validated_data["payment_method"],
                      ser.validated_data["payment_token"])
        order = self.get_queryset().get(pk=pk)
        return Response({"payment": PaymentSerializer(payment).data,
                         "order": OrderDetailSerializer(order, context={"request": request}).data},
                        status=201 if payment.status == payment.Status.SUCCEEDED else 402)

    @extend_schema(request=OtpSerializer, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="verify-otp", permission_classes=[IsCustomer])
    def verify_otp(self, request, pk=None):
        ser = OtpSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = services.verify_otp(self.get_queryset().get(pk=pk), ser.validated_data["code"])
        return Response(OrderDetailSerializer(self.get_queryset().get(pk=order.pk), context={"request": request}).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"], url_path="resend-otp", permission_classes=[IsCustomer])
    def resend_otp(self, request, pk=None):
        order = self.get_queryset().get(pk=pk)
        if order.status != OrderStatus.VERIFICATION_REQUIRED:
            raise DomainError("This order does not need verification.", code="not_required", status_code=409)
        services.issue_otp(order)
        return Response({"detail": "A new code was sent to your notifications."})

    @extend_schema(request=ReasonSerializer, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = self.get_queryset().get(pk=pk)
        reason = ser.validated_data.get("reason", "")
        order.cancel_reason = reason
        order.save(update_fields=["cancel_reason"])
        services.transition(order, OrderStatus.CANCELLED, services.actor_of(request.user), request.user,
                            note=reason or "Cancelled")
        return Response(OrderDetailSerializer(self.get_queryset().get(pk=pk), context={"request": request}).data)

    @extend_schema(request=ReasonSerializer, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"], url_path="return", permission_classes=[IsCustomer])
    def request_return(self, request, pk=None):
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = self.get_queryset().get(pk=pk)
        order.return_reason = ser.validated_data.get("reason", "")
        order.save(update_fields=["return_reason"])
        services.transition(order, OrderStatus.RETURN_REQUESTED, Role.CUSTOMER, request.user,
                            note=order.return_reason or "Return requested")
        return Response(OrderDetailSerializer(self.get_queryset().get(pk=pk), context={"request": request}).data)

    @extend_schema(request=TransitionSerializer, responses=OrderDetailSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsBackOffice])
    def transition(self, request, pk=None):
        ser = TransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        order = self.get_queryset().get(pk=pk)
        target = ser.validated_data["status"]
        if target not in OrderStatus.__members__:
            raise DomainError(f"Unknown status {target}.", code="invalid_status")
        if "fraud_confirmed" in ser.validated_data:
            order.fraud_confirmed = ser.validated_data["fraud_confirmed"]
            order.save(update_fields=["fraud_confirmed"])
        order = services.transition(order, target, Role(request.user.role), request.user,
                                    note=ser.validated_data.get("note", ""))
        if order.status == OrderStatus.PENDING:  # released from ON_HOLD
            order = services.advance_after_clearance(order)
        return Response(OrderDetailSerializer(self.get_queryset().get(pk=pk), context={"request": request}).data)

    @action(detail=False, methods=["get"], permission_classes=[IsBackOffice])
    def summary(self, request):
        rows = Order.objects.values("status").annotate(n=Count("id")).order_by("status")
        return Response({r["status"]: r["n"] for r in rows})
