"""Uniform JSON error responses: ``{"error": {"code": ..., "message": ...}}``."""

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class UpstreamError(Exception):
    """A third-party provider (routing, weather, geocoding) failed or is unavailable."""

    status_code = 502
    code = "upstream_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class PlanningError(UpstreamError):
    """The request is valid but cannot be planned (e.g. no road connection)."""

    status_code = 422
    code = "planning_error"


def exception_handler(exc, context):
    if isinstance(exc, UpstreamError):
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status_code)
    response = drf_exception_handler(exc, context)
    if response is not None:
        detail = response.data
        if isinstance(detail, dict) and "detail" in detail:
            message, fields = str(detail["detail"]), None
        else:
            message, fields = "Some fields are invalid.", detail
        response.data = {"error": {"code": "invalid_request", "message": message, "fields": fields}}
    return response
