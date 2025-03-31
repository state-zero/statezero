import os
from corsheaders.defaults import default_headers

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            os.path.join(BASE_DIR, "templates")
        ],  # adjust if you have custom templates
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",  # required by admin
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

STATIC_URL = "/static/"

SECRET_KEY = "fake-key"
DEBUG = True

STATEZERO_E2E_TESTING = False

TEST_DB_PATH = ""

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.admin",
    "django.contrib.staticfiles",
    "django.contrib.messages",
    "rest_framework",
    "rest_framework.authtoken",
    "tests.django_app",
    "statezero.adaptors.django",
    "corsheaders",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "db.sqlite3",
    }
}

# First, configure Django's cache
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',  # Fast in-memory cache
        'LOCATION': 'statezero-cache',
    },
    # For production with Redis:
    'redis': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://localhost:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-operation-id",
]

# Then configure StateZero to use one of these caches
STATEZERO_CACHE = {
    'NAME': 'default',
    'DEFAULT_TTL': 3600,
}

STATEZERO_PUSHER = {
    "APP_ID": os.getenv('PUSHER_APP_ID'),
    "KEY": os.getenv('PUSHER_KEY'),
    "SECRET": os.getenv('PUSHER_SECRET'),
    "CLUSTER": os.getenv('PUSHER_CLUSTER'),
}

ZEN_STRICT_SERIALIZATION = False # Used for testing statezero

STATEZERO_QUERY_TIMEOUT_MS = 1000  # Important, prevents trivial Ddos

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATEZERO_VIEW_ACCESS_CLASS = "rest_framework.permissions.IsAuthenticated"
STATEZERO_DEFAULT_USER_FUNC = "tests.django_app.test_user.get_or_create_test_user"

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "statezero.adaptors.django.middleware.OperationIDMiddleware",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
}

DEFAULT_CURRENCY = "USD"

ROOT_URLCONF = "tests.django_app.urls"
