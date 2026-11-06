from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from ..domain.recommend import CRITERIA
from ..domain.risk import rules_table
from ..planning import plan_heatmap, plan_trip
from ..services import geocoding, probe
from .serializers import (
    INTERVAL_CHOICES,
    MAX_LOAD_LB,
    GeocodeQuerySerializer,
    HeatmapRequestSerializer,
    PlanRequestSerializer,
)


@api_view(["GET"])
@throttle_classes([])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def upstreams(request):
    """Reachability of each third-party provider from this server (cached for a minute)."""
    results = probe.check_all()
    return Response({"ok": all(r["ok"] for r in results.values()), "providers": results})


@api_view(["GET"])
@throttle_classes([])
def rules(request):
    """Risk table, load rules and ranking criteria (single source of truth for UI legends)."""
    return Response(
        {
            **rules_table(),
            "ranking_criteria": [c.label for c in CRITERIA],
            "interval_choices": list(INTERVAL_CHOICES),
            "max_load_lb": MAX_LOAD_LB,
        }
    )


@api_view(["GET"])
@throttle_classes([])
def geocode(request):
    params = GeocodeQuerySerializer(data=request.query_params)
    params.is_valid(raise_exception=True)
    return Response({"results": geocoding.search(params.validated_data["q"], params.validated_data["limit"])})


@api_view(["POST"])
def plan(request):
    body = PlanRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    return Response(plan_trip(body.to_request()))


@api_view(["POST"])
def heatmap(request):
    body = HeatmapRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    data = body.validated_data
    return Response(plan_heatmap(data["departure_time"], data["load_weight_lb"], data["routes"], body.storm_or_none()))
