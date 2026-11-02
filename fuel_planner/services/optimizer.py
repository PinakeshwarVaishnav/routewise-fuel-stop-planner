"""Minimum-cost fuel-stop planning for a fixed driving route.

The route is a one-dimensional journey measured in miles from its start. We
project each nearby station onto that line, then use the classic greedy gas-
station strategy. The strategy is globally optimal for the assumptions below:

* The vehicle begins with a full 50-gallon tank (500-mile range).
* Fuel economy is constant at 10 miles per gallon.
* Fuel is divisible: a driver may buy any amount up to the tank's capacity.
* Fuel prices are fixed during the trip and there are no refuelling detours.
* We count fuel bought after departure; the starting tank was bought earlier.

At a station, look ahead up to one full tank. If a cheaper station is reachable,
buy only enough to reach the nearest such station. Otherwise buy enough to fill
the tank, then continue to the next station. The proof is simple: buying fuel
at a cheaper reachable station dominates buying those same gallons now; when
no cheaper station is reachable, today's price is no greater than any price
available before the next full-tank decision point, so filling now is best.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

DEFAULT_TANK_RANGE_MILES = 500.0
DEFAULT_MPG = 10.0
TANK_CAPACITY_GALLONS = DEFAULT_TANK_RANGE_MILES / DEFAULT_MPG
CENTS = Decimal("0.01")
DEFAULT_MIN_SAVING_PER_GALLON = 0.05


def _collapse_nearby_positions(
    candidates: list[dict[str, Any]],
    *,
    tolerance_miles: float = 0.1,
) -> list[dict[str, Any]]:
    """Keep the cheapest candidate for effectively the same route position.

    Multiple station records in one city receive the same Census place point.
    Without this collapse, they would appear as several artificial stations
    separated by zero miles. Choose the lowest price at that shared point.
    """
    ordered = sorted(
        candidates,
        key=lambda station: (
            float(station["route_position_miles"]),
            float(station["price_per_gallon"]),
        ),
    )
    grouped: list[dict[str, Any]] = []
    for station in ordered:
        position = float(station["route_position_miles"])
        if (
            grouped
            and position - float(grouped[-1]["route_position_miles"]) <= tolerance_miles
        ):
            old_price = float(grouped[-1]["price_per_gallon"])
            new_price = float(station["price_per_gallon"])
            if new_price < old_price:
                grouped[-1] = station
            continue
        grouped.append(station)
    return grouped


def _append_purchase(
    purchases: list[dict[str, Any]],
    station: dict[str, Any],
    gallons: float,
    fuel_on_arrival: float,
    next_position: float,
) -> None:
    """Record a real purchase; passing through a station is not a stop."""
    if gallons <= 1e-8:
        return

    price = Decimal(str(station["price_per_gallon"]))
    gallons_decimal = Decimal(str(gallons)).quantize(Decimal("0.000001"))
    cost = (price * gallons_decimal).quantize(CENTS, rounding=ROUND_HALF_UP)

    purchases.append(
        {
            "station_id": station["station_id"],
            "name": station["name"],
            "address": station["address"],
            "city": station["city"],
            "state": station["state"],
            "latitude": station["latitude"],
            "longitude": station["longitude"],
            "location_precision": station["location_precision"],
            "route_position_miles": round(float(station["route_position_miles"]), 2),
            "distance_from_route_miles": round(
                float(station["distance_from_route_miles"]), 2
            ),
            "price_per_gallon_usd": round(float(price), 8),
            "fuel_on_arrival_gallons": round(fuel_on_arrival, 6),
            "gallons_to_purchase": round(gallons, 6),
            "fuel_after_purchase_gallons": round(fuel_on_arrival + gallons, 6),
            "distance_to_next_stop_miles": round(
                next_position - float(station["route_position_miles"]), 2
            ),
            "estimated_purchase_cost_usd": str(cost),
        }
    )


def minimum_cost_fuel_plan(
    route_distance_miles: float,
    station_candidates: list[dict[str, Any]],
    *,
    tank_range_miles: float = DEFAULT_TANK_RANGE_MILES,
    miles_per_gallon: float = DEFAULT_MPG,
    min_saving_per_gallon: float = 0.0,
    min_purchase_gallons: float = 0.0,
) -> dict[str, Any]:
    """Return the globally cheapest feasible refuelling plan on this route.

    This is the standard one-route gas-station greedy algorithm, with the
    initial full tank handled explicitly. It does not greedily select the
    cheapest station in the whole corridor; it repeatedly makes the locally
    dominant decision described in the module docstring.

    Running time is O(n^2) in the number of candidate stations because each
    paid stop looks forward for the nearest cheaper station within one tank.
    For a route-corridor subset of a few dozen or a few hundred stations this
    is comfortably small, and it avoids an external optimization service.
    """
    if route_distance_miles < 0:
        raise ValueError("Route distance cannot be negative.")
    if tank_range_miles <= 0 or miles_per_gallon <= 0:
        raise ValueError("Tank range and fuel economy must be positive.")

    tank_capacity = tank_range_miles / miles_per_gallon
    total_fuel_used = route_distance_miles / miles_per_gallon

    if route_distance_miles <= tank_range_miles:
        return {
            "is_feasible": True,
            "stops": [],
            "total_fuel_used_gallons": round(total_fuel_used, 3),
            "initial_fuel_used_gallons": round(total_fuel_used, 3),
            "fuel_purchased_gallons": 0.0,
            "fuel_cost_usd": Decimal("0.00"),
            "reason": "The full starting tank is sufficient for the entire route.",
        }

    stations = [
        station
        for station in station_candidates
        if 0 <= float(station["route_position_miles"]) < route_distance_miles
        and float(station["price_per_gallon"]) > 0
    ]
    stations = _collapse_nearby_positions(stations)
    stations.sort(key=lambda station: float(station["route_position_miles"]))

    if not stations:
        return _unreachable_result(total_fuel_used, tank_capacity)

    # The starting tank is full. Drive to the first candidate station without
    # buying any fuel, because the vehicle has not yet reached a refuelling point.
    current_index = 0
    current_station = stations[current_index]
    current_position = float(current_station["route_position_miles"])
    if current_position > tank_range_miles + 1e-9:
        return _unreachable_result(total_fuel_used, tank_capacity)

    fuel_remaining = max(
        0.0,
        tank_capacity - current_position / miles_per_gallon,
    )
    purchases: list[dict[str, Any]] = []
    destination_reached = False

    while current_index < len(stations):
        current_station = stations[current_index]
        current_position = float(current_station["route_position_miles"])
        distance_to_destination = route_distance_miles - current_position

        # The current fuel is enough; buying anything else would be wasteful.
        if distance_to_destination <= fuel_remaining * miles_per_gallon + 1e-9:
            destination_reached = True
            break

        current_price = float(current_station["price_per_gallon"])
        next_cheaper_index: int | None = None

        # First cheaper station is the useful target. If we bought enough to
        # skip it, we would be replacing cheaper fuel there with today's fuel.
        for candidate_index in range(current_index + 1, len(stations)):
            candidate = stations[candidate_index]
            candidate_position = float(candidate["route_position_miles"])
            if candidate_position - current_position > tank_range_miles + 1e-9:
                break
            if (
                float(candidate["price_per_gallon"])
                < current_price - min_saving_per_gallon - 1e-9
            ):
                next_cheaper_index = candidate_index
                break

        if next_cheaper_index is not None:
            target_index = next_cheaper_index
            target_position = float(stations[target_index]["route_position_miles"])
            leg_distance = target_position - current_position
            gallons_needed = leg_distance / miles_per_gallon
            gallons_to_buy = max(0.0, gallons_needed - fuel_remaining)

            if gallons_to_buy > tank_capacity - fuel_remaining + 1e-7:
                return _unreachable_result(total_fuel_used, tank_capacity)

            # Practical rule: nobody stops to buy a splash of fuel. Round small
            # purchases up, but never beyond the tank or what the trip still needs.
            if 0 < gallons_to_buy < min_purchase_gallons:
                still_needed = (
                    distance_to_destination / miles_per_gallon - fuel_remaining
                )
                gallons_to_buy = max(
                    gallons_to_buy,
                    min(
                        min_purchase_gallons,
                        tank_capacity - fuel_remaining,
                        still_needed,
                    ),
                )

            _append_purchase(
                purchases,
                current_station,
                gallons_to_buy,
                fuel_remaining,
                target_position,
            )
            fuel_remaining += gallons_to_buy - gallons_needed
            current_index = target_index
            continue

        # No cheaper station is reachable with a full tank. If the destination
        # itself is within range, buy only what is needed to finish.
        if distance_to_destination <= tank_range_miles + 1e-9:
            gallons_needed = distance_to_destination / miles_per_gallon
            gallons_to_buy = max(0.0, gallons_needed - fuel_remaining)
            if gallons_to_buy > tank_capacity - fuel_remaining + 1e-7:
                return _unreachable_result(total_fuel_used, tank_capacity)

            _append_purchase(
                purchases,
                current_station,
                gallons_to_buy,
                fuel_remaining,
                route_distance_miles,
            )
            fuel_remaining += gallons_to_buy - gallons_needed
            destination_reached = True
            break

        # Current price is no higher than any station we can reach in one tank.
        # Fill here, then advance to the next station and reconsider prices.
        next_index = current_index + 1
        if next_index >= len(stations):
            return _unreachable_result(total_fuel_used, tank_capacity)
        next_position = float(stations[next_index]["route_position_miles"])
        leg_distance = next_position - current_position
        if leg_distance > tank_range_miles + 1e-9:
            return _unreachable_result(total_fuel_used, tank_capacity)

        gallons_to_buy = max(0.0, tank_capacity - fuel_remaining)
        # A nearly full tank is not worth a stop: skip the top-off when the
        # purchase is tiny and the current fuel already reaches the next station.
        skip_top_off = (
            gallons_to_buy < min_purchase_gallons
            and leg_distance / miles_per_gallon <= fuel_remaining + 1e-9
        )
        if skip_top_off:
            fuel_remaining -= leg_distance / miles_per_gallon
            current_index = next_index
            continue

        _append_purchase(
            purchases,
            current_station,
            gallons_to_buy,
            fuel_remaining,
            next_position,
        )
        fuel_remaining = max(0.0, tank_capacity - leg_distance / miles_per_gallon)
        current_index = next_index

    if not destination_reached:
        return _unreachable_result(total_fuel_used, tank_capacity)

    purchased_gallons = sum(float(stop["gallons_to_purchase"]) for stop in purchases)
    total_cost = sum(
        (Decimal(stop["estimated_purchase_cost_usd"]) for stop in purchases),
        Decimal("0.00"),
    ).quantize(CENTS, rounding=ROUND_HALF_UP)

    # Fuel accounting is an important invariant: the route burns distance/mpg
    # gallons; the first 50 gallons come from the full starting tank.
    expected_purchases = max(0.0, total_fuel_used - tank_capacity)
    if abs(purchased_gallons - expected_purchases) > 0.02:
        raise AssertionError(
            "Fuel accounting invariant failed: fuel purchases do not match route consumption."
        )

    return {
        "is_feasible": True,
        "stops": purchases,
        "total_fuel_used_gallons": round(total_fuel_used, 3),
        "initial_fuel_used_gallons": round(min(total_fuel_used, tank_capacity), 3),
        "fuel_purchased_gallons": round(purchased_gallons, 3),
        "fuel_cost_usd": total_cost,
        "reason": "The selected stops minimize the modeled cost of en-route fuel purchases.",
    }


def _unreachable_result(total_fuel_used: float, tank_capacity: float) -> dict[str, Any]:
    """Use one consistent response when the supplied station data has a gap."""
    return {
        "is_feasible": False,
        "stops": [],
        "total_fuel_used_gallons": round(total_fuel_used, 3),
        "initial_fuel_used_gallons": round(min(total_fuel_used, tank_capacity), 3),
        "fuel_purchased_gallons": 0.0,
        "fuel_cost_usd": None,
        "reason": (
            "The available stations do not form a chain with gaps of 500 miles or less. "
            "The vehicle cannot complete this route with the supplied station data."
        ),
    }


def with_total_trip_cost(
    plan: dict[str, Any],
    reference_price_per_gallon: float | None,
    basis: str,
) -> dict[str, Any]:
    """Add the cost of ALL fuel burned, not just fuel bought after departure.

    The fuel in the starting tank is priced at ``reference_price_per_gallon``
    (the CSV has no price for the starting location), so a short trip that needs
    no stops still reports a realistic fuel cost.
    """
    en_route = plan["fuel_cost_usd"]
    if en_route is None or reference_price_per_gallon is None:
        return {
            **plan,
            "starting_tank_cost_usd": None,
            "total_trip_cost_usd": None,
            "starting_fuel_price_basis": basis,
        }
    starting = (
        Decimal(str(plan["initial_fuel_used_gallons"]))
        * Decimal(str(reference_price_per_gallon))
    ).quantize(CENTS, rounding=ROUND_HALF_UP)
    return {
        **plan,
        "starting_tank_cost_usd": starting,
        "total_trip_cost_usd": (en_route + starting).quantize(CENTS),
        "starting_fuel_price_basis": basis,
    }
