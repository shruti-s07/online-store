import threading

from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.shared.errors import DomainError
from backend.shared.permissions import IsAdmin, IsBackOffice

from .models import JobRun
from .runner import JOBS


class JobRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobRun
        fields = ["id", "name", "status", "detail", "started_at", "finished_at"]


class JobRunListView(ListAPIView):
    permission_classes = [IsBackOffice]
    serializer_class = JobRunSerializer

    def get_queryset(self):
        qs = JobRun.objects.all()
        if self.request.query_params.get("name"):
            qs = qs.filter(name=self.request.query_params["name"])
        return qs


class TriggerJobView(APIView):
    """Run a job now (in a background thread; training can take minutes)."""

    permission_classes = [IsAdmin]

    def post(self, request, name: str):
        if name not in JOBS:
            raise DomainError(f"Unknown job {name}.", code="not_found", status_code=404)
        if JobRun.objects.filter(name=name, status=JobRun.Status.RUNNING).exists():
            raise DomainError("This job is already running.", code="already_running", status_code=409)
        threading.Thread(target=JOBS[name], daemon=True).start()
        return Response({"detail": f"{name} started", "jobs": list(JOBS)}, status=202)


class ModelCatalogView(APIView):
    """Metadata JSON of every trained artifact (date, data hash, params, metrics)."""

    permission_classes = [IsBackOffice]

    def get(self, request):
        from ai.common import load_meta
        from ai.embedding import get_embedder
        from ai.train import STEPS
        from backend.folder_two_services.assistant.engine import engine_name
        names = STEPS + ["fake_review_heuristics", "price_elasticity"]
        return Response({"models": {n: load_meta(n) for n in names}, "assistant_engine": engine_name(),
                         "image_embedding": get_embedder().name})
