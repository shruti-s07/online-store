from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


CORE = ["accounts", "catalog", "inventory", "cart", "orders"]
SERVICES = ["reports", "discounts", "reviews", "risk", "forecasting", "segmentation", "recommendations",
            "snapcheck", "assistant", "jobs"]

api = [path("", include(f"backend.folder_one_core.{a}.urls")) for a in CORE]
api += [path("", include(f"backend.folder_two_services.{a}.urls")) for a in SERVICES]

urlpatterns = [
    path("api/", include(api)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    # Local-only project: Django serves catalogue images directly. Customer uploads
    # (SnapCheck photos) are NOT under products/ and are only reachable through the API.
    re_path(r"^%s(?P<path>products/.*)$" % settings.MEDIA_URL.lstrip("/"), serve,
            {"document_root": settings.MEDIA_ROOT}),
]
