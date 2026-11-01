from django.db import models


class FuelStation(models.Model):
    """A station from the supplied assessment CSV.

    The source has no coordinates. Unless manually overridden with an exact
    coordinate file, latitude/longitude are Census place internal points and
    must therefore be treated as approximate, not as the pump entrance.
    """

    class LocationPrecision(models.TextChoices):
        PLACE_POINT = "place_point", "Census place internal point (approximate)"
        EXACT = "exact", "Exact station coordinates"

    station_id = models.PositiveBigIntegerField(unique=True)
    name = models.CharField(max_length=180)
    address = models.CharField(max_length=180, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    price_per_gallon = models.DecimalField(max_digits=12, decimal_places=8)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    location_precision = models.CharField(
        max_length=16,
        choices=LocationPrecision.choices,
        default=LocationPrecision.PLACE_POINT,
    )
    source_observations = models.PositiveSmallIntegerField(default=1)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("state", "city", "name")
        indexes = [
            models.Index(fields=("state", "city"), name="station_state_city_idx"),
            models.Index(fields=("latitude", "longitude"), name="station_lat_lon_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} — {self.city}, {self.state} (${self.price_per_gallon}/gal)"
