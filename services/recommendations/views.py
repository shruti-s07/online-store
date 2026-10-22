from rest_framework.response import Response
from rest_framework.views import APIView

from backend.shared.permissions import IsAnyRole, IsCustomer

from . import service


class MyRecommendationsView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request):
        return Response(service.for_user(request.user))


class SimilarProductsView(APIView):
    permission_classes = [IsAnyRole]

    def get(self, request, product_id: int):
        return Response(service.similar_products(product_id))
