"""Settings for RouteWise.

Keep secrets in environment variables. The local defaults are convenient for
an assessment demo, not a production deployment.
"""

from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-local-development-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "fuel_planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# LocMemCache is sufficient for a single-process assessment demo. Use Redis
# when deploying multiple application workers so all workers share route cache.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "routewise-api-cache",
        "TIMEOUT": 60 * 60,
    }
}

ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_BASE_URL = "https://api.openrouteservice.org"
ORS_GEOCODE_CACHE_SECONDS = 60 * 60 * 24 * 30
ORS_ROUTE_CACHE_SECONDS = 60 * 60 * 24
# Stations farther than this from the route are ignored: detours cost fuel and time.
MAX_STATION_DEVIATION_MILES = float(os.getenv("MAX_STATION_DEVIATION_MILES", "5"))
# A cheaper station only changes the plan if it saves at least this much per gallon.
# This avoids absurd stops that buy under a gallon to save a cent.
MIN_PRICE_SAVING_PER_GALLON = float(os.getenv("MIN_PRICE_SAVING_PER_GALLON", "0.05"))
# Smallest purchase worth stopping for (gallons); smaller buys are rounded up.
MIN_PURCHASE_GALLONS = float(os.getenv("MIN_PURCHASE_GALLONS", "5"))
# Route line sent to the browser is simplified to this tolerance (miles).
ROUTE_SIMPLIFY_TOLERANCE_MILES = 0.25

# Django's default ("same-origin") strips the Referer header, and the public
# OpenStreetMap tile servers answer 403 "Access blocked" without one.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "600/hour",
    },
}

# Allow external map tile providers to receive the page origin.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
