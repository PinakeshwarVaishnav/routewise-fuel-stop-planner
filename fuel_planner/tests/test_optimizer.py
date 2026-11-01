from django.test import SimpleTestCase

from fuel_planner.services.optimizer import minimum_cost_fuel_plan


def station(station_id, position, price, city):
    return {
        "station_id": station_id,
        "name": f"{city} Travel Center",
        "address": f"I-{station_id} exit",
        "city": city,
        "state": "TX",
        "price_per_gallon": price,
        "latitude": 30.0,
        "longitude": -97.0,
        "location_precision": "exact",
        "route_position_miles": position,
        "distance_from_route_miles": 0.2,
    }


class FuelOptimizerTests(SimpleTestCase):
    def test_full_starting_tank_covers_short_route(self):
        result = minimum_cost_fuel_plan(
            420,
            [station(1, 100, 3.10, "Austin")],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["fuel_purchased_gallons"], 0.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "0.00")

    def test_optimizer_can_skip_a_cheaper_but_unnecessary_intermediate_stop(self):
        result = minimum_cost_fuel_plan(
            650,
            [
                station(1, 100, 4.00, "Expensive One Hundred"),
                station(2, 450, 2.00, "Cheap Four Fifty"),
                station(3, 600, 4.00, "Expensive Six Hundred"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [2])
        self.assertEqual(result["fuel_purchased_gallons"], 15.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "30.00")
        self.assertEqual(result["stops"][0]["gallons_to_purchase"], 15.0)

    def test_global_plan_uses_two_stops_when_that_is_cheaper(self):
        result = minimum_cost_fuel_plan(
            900,
            [
                station(1, 100, 4.00, "Expensive One Hundred"),
                station(2, 400, 2.00, "Cheap Four Hundred"),
                station(3, 600, 3.00, "Middle Six Hundred"),
                station(4, 800, 1.00, "Cheapest Eight Hundred"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [2, 4])
        self.assertEqual(result["fuel_purchased_gallons"], 40.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "70.00")
        self.assertTrue(
            all(stop["gallons_to_purchase"] > 0 for stop in result["stops"])
        )

    def test_carries_remaining_fuel_forward_before_buying_at_a_higher_price(self):
        result = minimum_cost_fuel_plan(
            900,
            [
                station(1, 100, 2.00, "Low Price One Hundred"),
                station(2, 400, 2.10, "Slightly Higher Four Hundred"),
                station(3, 600, 3.00, "Expensive Six Hundred"),
                station(4, 850, 1.00, "Cheapest Eight Fifty"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [1, 2, 4])
        self.assertEqual(result["fuel_purchased_gallons"], 40.0)
        self.assertEqual(str(result["fuel_cost_usd"]), "77.50")

    def test_reports_unreachable_route_when_station_gaps_exceed_tank_range(self):
        result = minimum_cost_fuel_plan(
            1100,
            [
                station(1, 100, 3.00, "First Town"),
                station(2, 700, 3.00, "Second Town"),
            ],
        )

        self.assertFalse(result["is_feasible"])
        self.assertEqual(result["stops"], [])
        self.assertIsNone(result["fuel_cost_usd"])

    def test_same_city_marker_uses_only_the_cheapest_candidate(self):
        result = minimum_cost_fuel_plan(
            700,
            [
                station(1, 250.01, 4.20, "Same City"),
                station(2, 250.05, 2.20, "Same City"),
            ],
        )

        self.assertTrue(result["is_feasible"])
        self.assertEqual(result["stops"][0]["station_id"], 2)

    def test_rejects_invalid_vehicle_parameters(self):
        with self.assertRaises(ValueError):
            minimum_cost_fuel_plan(100, [], tank_range_miles=0)
