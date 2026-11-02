from django.test import SimpleTestCase

from fuel_planner.services.geometry import haversine_miles, project_point_onto_route


class GeometryTests(SimpleTestCase):
    def test_haversine_distance_for_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_miles(0, 0, 1, 0), 69.09, delta=0.2)

    def test_projects_a_point_onto_a_straight_east_west_route(self):
        # ORS coordinates are [longitude, latitude]. The point is north of
        # the middle of the route, so its route mileage should be about half.
        route = [[-100.0, 35.0], [-99.0, 35.0]]
        route_position, distance_from_route = project_point_onto_route(
            35.1, -99.5, route
        )

        self.assertAlmostEqual(route_position, 28.2, delta=0.5)
        self.assertAlmostEqual(distance_from_route, 6.9, delta=0.2)


class SimplifyRouteTests(SimpleTestCase):
    def test_straight_line_collapses_and_endpoints_are_kept(self):
        from fuel_planner.services.geometry import simplify_route
        line = [[-100 + i * 0.01, 35.0] for i in range(1000)]
        out = simplify_route(line, 0.25)
        self.assertEqual(out[0], [-100.0, 35.0])
        self.assertEqual(out[-1], [round(line[-1][0], 5), 35.0])
        self.assertLess(len(out), 5)
