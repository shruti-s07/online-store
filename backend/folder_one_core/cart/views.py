from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.shared.permissions import IsCustomer

from . import services


class AddItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class QuantitySerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField(allow_blank=True, max_length=40)


class CartView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request):
        return Response(services.price_cart(request.user))

    def delete(self, request):
        services.clear(request.user)
        return Response(services.price_cart(request.user))


class CartItemsView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=AddItemSerializer)
    def post(self, request):
        ser = AddItemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.set_quantity(request.user, ser.validated_data["product_id"], ser.validated_data["quantity"], increment=True)
        return Response(services.price_cart(request.user), status=201)


class CartItemView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=QuantitySerializer)
    def patch(self, request, product_id: int):
        ser = QuantitySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.set_quantity(request.user, product_id, ser.validated_data["quantity"])
        return Response(services.price_cart(request.user))

    def delete(self, request, product_id: int):
        services.remove(request.user, product_id)
        return Response(services.price_cart(request.user))


class DiscountCodeView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=CodeSerializer)
    def post(self, request):
        ser = CodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        services.set_discount_code(request.user, ser.validated_data["code"])
        return Response(services.price_cart(request.user))
