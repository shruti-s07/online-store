from rest_framework.response import Response
from rest_framework.views import APIView

from backend.shared.errors import DomainError
from backend.shared.permissions import IsBackOffice

from . import service


class ForecastView(APIView):
    permission_classes = [IsBackOffice]

    def get(self, request, product_id: int):
        f = service.product_forecast(product_id)
        if f is None:
            raise DomainError("No forecast for this product.", code="not_found", status_code=404)
        return Response(f)


class RestockView(APIView):
    permission_classes = [IsBackOffice]

    def get(self, request):
        return Response({"horizon_days": service.horizon_days(),
                         "results": service.restock_suggestions(request.query_params.get("all") != "true")})


class ForecastSummaryView(APIView):
    permission_classes = [IsBackOffice]

    def get(self, request):
        return Response(service.model_summary())
