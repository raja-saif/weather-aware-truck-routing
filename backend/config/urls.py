from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.generic import TemplateView


def _spa_missing(request):
    return HttpResponse(
        "Frontend not built. Run `npm run build` in /frontend, or use the Vite dev server on :5173.",
        content_type="text/plain",
        status=503,
    )


spa = TemplateView.as_view(template_name="index.html") if (settings.FRONTEND_DIST / "index.html").exists() else _spa_missing

urlpatterns = [
    path("api/", include("planner.api.urls")),
    # Everything else is the React single-page app (assets are served by WhiteNoise).
    re_path(r"^(?!api/|static/).*$", spa),
]
