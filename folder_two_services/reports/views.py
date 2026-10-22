from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.shared.errors import DomainError
from backend.shared.permissions import IsAnyRole, IsBackOffice
from backend.shared.roles import Role

from .export import to_csv, to_pdf
from .functions import REPORTS, order_history, run_report

EXPORT = OpenApiParameter("export", str, enum=["csv", "pdf"], required=False)


def respond(request, report: dict):
    fmt = request.query_params.get("export")
    if fmt == "csv":
        resp = HttpResponse(to_csv(report), content_type="text/csv")
    elif fmt == "pdf":
        resp = HttpResponse(to_pdf(report), content_type="application/pdf")
    else:
        return Response(report)
    resp["Content-Disposition"] = f'attachment; filename="{report["report"]}.{fmt}"'
    return resp


class ReportListView(APIView):
    permission_classes = [IsBackOffice]

    def get(self, request):
        return Response([{"name": k, "description": v.description, "params": list(v.params)} for k, v in REPORTS.items()])


class ReportView(APIView):
    permission_classes = [IsBackOffice]

    @extend_schema(parameters=[EXPORT])
    def get(self, request, name: str):
        if name not in REPORTS:
            raise DomainError(f"Unknown report {name}.", code="not_found", status_code=404)
        return respond(request, run_report(name, **request.query_params.dict()))


class MyOrderHistoryView(APIView):
    """Customers' own order-history report (same export formats)."""

    permission_classes = [IsAnyRole]

    @extend_schema(parameters=[EXPORT])
    def get(self, request):
        user = request.user if request.user.role == Role.CUSTOMER else None
        report = order_history(days=request.query_params.get("days") or 3650, user=user)
        report["report"] = "my_orders"
        return respond(request, report)
