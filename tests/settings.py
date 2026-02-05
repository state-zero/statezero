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

USE_TZ = True
TIME_ZONE = 'UTC'

STATIC_URL = "/static/"

SECRET_KEY = "fake-key"
DEBUG = True

STATEZERO_E2E_TESTING = False
STATEZERO_ENABLE_TELEMETRY = True
STATEZERO_SYNC_TOKEN = "test-secret-token"

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
    "storages",  # Add django-storages
]

# Add simple_history if installed
try:
    import simple_history
    INSTALLED_APPS.insert(INSTALLED_APPS.index("tests.django_app"), "simple_history")
except ImportError:
    pass

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "db.sqlite3",
    }
}

# First, configure Django's cache
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'statezero-cache',
    }
}

CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-operation-id",
    "x-canonical-id",
    "x-statezero-sync-token"
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

# Django Storages Configuration for DigitalOcean Spaces
AWS_ACCESS_KEY_ID = os.getenv('SPACES_ACCESS_KEY')
AWS_SECRET_ACCESS_KEY = os.getenv('SPACES_SECRET_KEY')
AWS_STORAGE_BUCKET_NAME = 'state-zero'
AWS_S3_ENDPOINT_URL = 'https://fra1.digitaloceanspaces.com'
AWS_S3_REGION_NAME = 'fra1'

# Security settings
AWS_DEFAULT_ACL = 'private'
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400'
}

STATEZERO_STORAGE_KEY = 'default'

# File storage settings
AWS_S3_FILE_OVERWRITE = False
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 3600 

# Media files configuration
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
MEDIA_URL = 'https://state-zero.fra1.digitaloceanspaces.com/'

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
