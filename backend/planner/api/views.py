from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from ..domain.risk import rules_table


@api_view(["GET"])
@throttle_classes([])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@throttle_classes([])
def rules(request):
    """Risk table and load rules (single source of truth for UI legends)."""
    return Response(rules_table())
