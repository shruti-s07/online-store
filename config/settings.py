"""Django settings. All values come from .env or config/*.yaml via config.loader."""
from datetime import timedelta

from config import loader
from config.loader import business, env, env_bool, env_list, project_path

BASE_DIR = loader.ROOT
B = business()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

CORE_APPS = [
    "backend.folder_one_core.accounts",
    "backend.folder_one_core.catalog",
    "backend.folder_one_core.inventory",
    "backend.folder_one_core.cart",
    "backend.folder_one_core.reservations",
    "backend.folder_one_core.orders",
    "backend.folder_one_core.payments",
]
SERVICE_APPS = [
    "backend.folder_two_services.reports",
    "backend.folder_two_services.discounts",
    "backend.folder_two_services.reviews",
    "backend.folder_two_services.risk",
    "backend.folder_two_services.forecasting",
    "backend.folder_two_services.segmentation",
    "backend.folder_two_services.recommendations",
    "backend.folder_two_services.snapcheck",
    "backend.folder_two_services.assistant",
    "backend.folder_two_services.jobs",
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    *CORE_APPS,
    *SERVICE_APPS,
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "backend.urls"
WSGI_APPLICATION = "backend.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

DB_ENGINE = env("DB_ENGINE", "django.db.backends.postgresql")

if "sqlite" in DB_ENGINE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": project_path(env("DB_NAME", "online_store.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT"),
            "OPTIONS": {"connect_timeout": env("DB_CONNECT_TIMEOUT", cast=int)},
        }
    }

AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": B["auth"]["password_min_length"]},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = B["locale"]["time_zone"]
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = env("MEDIA_URL")
MEDIA_ROOT = project_path(env("MEDIA_ROOT"))
DATA_UPLOAD_MAX_MEMORY_SIZE = B["api"]["max_upload_mb"] * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Deny-by-default; every view declares its own role-based permission classes.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "backend.shared.pagination.ConfigPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "login": B["auth"]["login_rate"],
        "register": B["auth"]["register_rate"],
    },
    "EXCEPTION_HANDLER": "backend.shared.errors.exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=B["auth"]["access_token_minutes"]),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=B["auth"]["refresh_token_days"]),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": SECRET_KEY,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Online Store Database API",
    "DESCRIPTION": "Simulated e-commerce backend: core commerce + AI services.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL")},
}
