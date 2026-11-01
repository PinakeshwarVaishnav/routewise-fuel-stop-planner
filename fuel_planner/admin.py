from django.contrib import admin
from .models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = (
        "station_id",
        "name",
        "city",
        "state",
        "price_per_gallon",
        "location_precision",
    )
    list_filter = ("state", "location_precision")
    search_fields = ("name", "city", "station_id")
    ordering = ("state", "city", "name")
