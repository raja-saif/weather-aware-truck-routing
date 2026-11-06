"""Request validation for the public API."""

from __future__ import annotations

from rest_framework import serializers

from ..domain.scenario import Storm
from ..planning import Place, TripRequest, departure_bounds
from ..services import geocoding

INTERVAL_CHOICES = (10, 25, 50)
MAX_LOAD_LB = 120_000


class PlaceSerializer(serializers.Serializer):
    """A place picked from suggestions (lat/lon given) or free text to geocode."""

    label = serializers.CharField(max_length=300, required=False, allow_blank=True)
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False)

    def validate(self, attrs):
        has_coords = "lat" in attrs and "lon" in attrs
        if not has_coords and not attrs.get("label", "").strip():
            raise serializers.ValidationError("Enter a place or pick one from the suggestions.")
        return attrs

    def to_place(self, attrs) -> Place:
        if "lat" in attrs and "lon" in attrs:
            return Place(attrs["lat"], attrs["lon"], attrs.get("label") or f"{attrs['lat']:.4f}, {attrs['lon']:.4f}")
        lat, lon, label = geocoding.resolve(attrs["label"])
        return Place(lat, lon, label)


class StormSerializer(serializers.Serializer):
    """The demo storm exactly as the plan response returned it (bounded to sane values)."""

    lat = serializers.FloatField(min_value=-85, max_value=85)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    t0 = serializers.FloatField()
    v_north_mph = serializers.FloatField(min_value=-60, max_value=60)
    v_east_mph = serializers.FloatField(min_value=-60, max_value=60)
    radius_mi = serializers.FloatField(min_value=10, max_value=400)
    wind_add_mph = serializers.FloatField(min_value=0, max_value=100)
    gust_add_mph = serializers.FloatField(min_value=0, max_value=120)
    rain_add_in = serializers.FloatField(min_value=0, max_value=3)
    snow_add_in = serializers.FloatField(min_value=0, max_value=6)

    def to_storm(self, attrs) -> Storm:
        return Storm(**attrs)


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=INTERVAL_CHOICES, default=25)
    hos_breaks = serializers.BooleanField(default=True)
    scenario = serializers.ChoiceField(choices=("live", "storm"), default="live")
    # Re-planning a demo-storm trip (e.g. a later departure) keeps the same storm.
    storm = StormSerializer(required=False, allow_null=True)

    def validate_departure_time(self, value):
        earliest, latest = departure_bounds()
        if value < earliest:
            raise serializers.ValidationError("Departure time is in the past.")
        if value > latest:
            raise serializers.ValidationError("Departure must be within the next 7 days (forecast range).")
        return value

    def to_request(self) -> TripRequest:
        data = self.validated_data
        place = PlaceSerializer()
        return TripRequest(
            origin=place.to_place(data["origin"]),
            destination=place.to_place(data["destination"]),
            departure=data["departure_time"],
            load_lb=data["load_weight_lb"],
            interval_mi=int(data["interval_miles"]),
            hos=data["hos_breaks"],
            scenario=data["scenario"],
            storm=StormSerializer().to_storm(data["storm"]) if data.get("storm") else None,
        )


class LonLatField(serializers.ListField):
    child = serializers.FloatField()
    min_length = 2
    max_length = 2

    def to_internal_value(self, data):
        lon, lat = super().to_internal_value(data)
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise serializers.ValidationError("Coordinate out of range.")
        return [lon, lat]


class HeatmapRequestSerializer(serializers.Serializer):
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    routes = serializers.ListField(
        child=serializers.ListField(child=LonLatField(), min_length=2, max_length=5000),
        min_length=1,
        max_length=3,
    )
    storm = StormSerializer(required=False, allow_null=True)

    validate_departure_time = PlanRequestSerializer.validate_departure_time

    def storm_or_none(self) -> Storm | None:
        attrs = self.validated_data.get("storm")
        return StormSerializer().to_storm(attrs) if attrs else None


class GeocodeQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=200)
    limit = serializers.IntegerField(min_value=1, max_value=10, default=6)
