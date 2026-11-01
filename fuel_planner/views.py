from __future__ import annotations

from django.conf import settings
from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .models import FuelStation
from .serializers import PlanRequestSerializer
from .services.geometry import stations_near_route
from .services.optimizer import minimum_cost_fuel_plan
from .services.ors_client import (
    LocationNotFound,
    OpenRouteServiceClient,
    ProviderUnavailable,
)


class RoutePlanThrottle(AnonRateThrottle):
    scope = "anon"


def home(request):
    """Serve a simple browser demo that calls the exact same JSON endpoint."""
    return render(request, "fuel_planner/index.html")


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "RouteWise fuel planner"})


@api_view(["POST"])
@throttle_classes([RoutePlanThrottle])
def plan_route(request):
    """Return one driving route and its minimum-cost feasible fuel plan."""
    serializer = PlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    start_query = serializer.validated_data["start"]
    finish_query = serializer.validated_data["finish"]
    provider = OpenRouteServiceClient()

    try:
        # These calls use separate caches. On a cold request we make two
        # geocoding calls and exactly one driving-directions call.
        start = provider.geocode_us(start_query)
        finish = provider.geocode_us(finish_query)
        route = provider.driving_route(start, finish)
    except LocationNotFound as exc:
        return Response(
            {"error": "location_not_found", "detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except ProviderUnavailable as exc:
        return Response(
            {"error": "routing_provider_unavailable", "detail": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    distance_miles = route["distance_meters"] / 1609.344
    route_coordinates = route["coordinates"]

    # The database query runs locally. We never ask the routing provider for
    # station coordinates, and we do not make one API call per station.
    stations = FuelStation.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
    ).only(
        "station_id",
        "name",
        "address",
        "city",
        "state",
        "price_per_gallon",
        "latitude",
        "longitude",
        "location_precision",
    )

    nearby_stations = stations_near_route(
        stations,
        route_coordinates,
        max_deviation_miles=settings.MAX_STATION_DEVIATION_MILES,
    )
    fuel_plan = minimum_cost_fuel_plan(distance_miles, nearby_stations)

    warnings = [
        (
            "Fuel prices are taken from the supplied CSV. It has no price timestamp; "
            "when a station ID occurs more than once, the importer keeps its lowest "
            "observed value. Prices should not be interpreted as live quotes."
        ),
        (
            "The supplied CSV contains no station coordinates. Unless a station has "
            "an exact coordinate override, its map pin is the U.S. Census place "
            "internal point for its city/state and is only an approximate location. "
            "Confirm the station address before travelling."
        ),
        (
            f"Candidate stations are retained only when their representative point "
            f"is within {settings.MAX_STATION_DEVIATION_MILES:g} miles of the route. "
            "This is a screening radius, not a promise that the station is directly "
            "beside the highway."
        ),
        (
            "The vehicle is assumed to start with a full 50-gallon tank. The reported "
            "trip fuel cost includes fuel purchased after departure, not the fuel "
            "already in the starting tank."
        ),
    ]

    selected_precision = {stop["location_precision"] for stop in fuel_plan["stops"]}
    if "place_point" in selected_precision:
        warnings.append(
            "At least one selected fuel-stop marker is approximate (city/place-level), "
            "not an exact pump location."
        )

    return Response(
        {
            "origin": start,
            "destination": finish,
            "route": {
                "type": "LineString",
                "coordinates": route_coordinates,
                "distance_miles": round(distance_miles, 2),
                "distance_kilometers": round(distance_miles * 1.609344, 2),
                "duration_seconds": round(route["duration_seconds"]),
                "duration_hours": round(route["duration_seconds"] / 3600, 2),
            },
            "vehicle": {
                "maximum_range_miles": 500,
                "fuel_economy_miles_per_gallon": 10,
                "tank_capacity_gallons": 50,
                "starting_tank": "full",
            },
            "fuel_plan": {
                "is_feasible": fuel_plan["is_feasible"],
                "reason": fuel_plan["reason"],
                "stops": fuel_plan["stops"],
                "stop_count": len(fuel_plan["stops"]),
                "total_fuel_used_gallons": fuel_plan["total_fuel_used_gallons"],
                "initial_fuel_used_gallons": fuel_plan["initial_fuel_used_gallons"],
                "fuel_purchased_gallons": fuel_plan["fuel_purchased_gallons"],
                "fuel_cost_usd": (
                    str(fuel_plan["fuel_cost_usd"])
                    if fuel_plan["fuel_cost_usd"] is not None
                    else None
                ),
            },
            "data_quality": {
                "geolocated_station_count": len(nearby_stations),
                "station_location_method": "Census place internal point unless exact override",
                "fuel_price_policy": "lowest observed price per station ID in supplied CSV",
            },
            "warnings": warnings,
            "provider_calls_on_cache_miss": {
                "geocoding": 2,
                "directions": 1,
                "total": 3,
            },
        }
    )
