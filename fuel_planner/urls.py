from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/v1/health/", views.health, name="health"),
    path("api/v1/plan/", views.plan_route, name="plan-route"),
]
