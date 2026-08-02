from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)

environ.Env.read_env(BASE_DIR / ".env")


SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="unsafe-development-key-change-before-deployment",
)

DEBUG = env.bool("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "0.0.0.0"],
)


DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "corsheaders",
    "drf_spectacular",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
]

LOCAL_APPS = [
    "accounts",
    "authentication",
    "markets",
    "notifications",
    "onboarding",
    "profiles",
    "sports",
    "system",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
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
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}


AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": ("django.contrib.auth.password_validation.UserAttributeSimilarityValidator"),
    },
    {
        "NAME": ("django.contrib.auth.password_validation.MinimumLengthValidator"),
    },
    {
        "NAME": ("django.contrib.auth.password_validation.CommonPasswordValidator"),
    },
    {
        "NAME": ("django.contrib.auth.password_validation.NumericPasswordValidator"),
    },
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"
USE_I18N = True
USE_TZ = True


STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173"],
)

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:5173"],
)


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "League OS API",
    "DESCRIPTION": "Sports, fantasy, ticketing and markets platform API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "MarketScopeEnum": ("markets.models.MarketScope.choices"),
        "MarketStatusEnum": [
            ("DRAFT", "Draft"),
            (
                "PENDING_APPROVAL",
                "Pending approval",
            ),
            ("APPROVED", "Approved"),
            ("OPEN", "Open"),
            ("SUSPENDED", "Suspended"),
            ("CLOSED", "Closed"),
            ("RESOLVED", "Resolved"),
            ("VOIDED", "Voided"),
            ("REJECTED", "Rejected"),
        ],
        "MarketTransitionActionEnum": [
            (
                "SUBMIT",
                "Submit for approval",
            ),
            ("APPROVE", "Approve"),
            ("REJECT", "Reject"),
            ("OPEN", "Open"),
            ("SUSPEND", "Suspend"),
            ("REOPEN", "Reopen"),
            ("CLOSE", "Close"),
        ],
    },
}


# Email Configuration
if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@leagueos.com")


# Registration and OTP Settings
OTP_RESEND_COOLDOWN_MINUTES = 2
OTP_MAX_DAILY_RESENDS = 5
OTP_MAX_VERIFICATION_ATTEMPTS = 5
OTP_EXPIRY_MINUTES = 10

# Login Throttling Settings
LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15

# Password Reset Settings
PASSWORD_RESET_OTP_EXPIRY_MINUTES = 15
PASSWORD_RESET_MAX_ATTEMPTS = 5

# =============================================================================
# Profile & Avatar Settings
# =============================================================================

# Minimum age for new profiles (in years)
PROFILE_MIN_AGE_YEARS = env.int("PROFILE_MIN_AGE_YEARS", default=13)

# Maximum upload size for avatars (in bytes) - 5 MB
AVATAR_MAX_UPLOAD_SIZE = env.int("AVATAR_MAX_UPLOAD_SIZE", default=5 * 1024 * 1024)

# Default avatar URL served by frontend when no avatar is set
DEFAULT_AVATAR_URL = env(
    "DEFAULT_AVATAR_URL",
    default="https://cdn.leagueos.com/avatars/default.png",
)

# Image dimension constraints
AVATAR_MAX_DIMENSION = 4096
AVATAR_MIN_DIMENSION = 256

# Allowed MIME types and extensions for avatars
AVATAR_ALLOWED_MIME_TYPES = [
    "image/jpeg",
    "image/png",
    "image/webp",
]
AVATAR_ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]

# Storage backend selection (local, s3, minio, r2)
STORAGE_BACKEND = env("STORAGE_BACKEND", default="local")

# Default file storage backend
if STORAGE_BACKEND == "local":
    DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
elif STORAGE_BACKEND in ("s3", "minio", "r2"):
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

# S3 / MinIO / R2 connection settings
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="")
AWS_S3_SIGNATURE_VERSION = env("AWS_S3_SIGNATURE_VERSION", default="s3v4")
AWS_S3_FILE_OVERWRITE = False
AWS_QUERYSTRING_AUTH = False
AWS_DEFAULT_ACL = "private"
AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", default="")
AWS_MEDIA_LOCATION = "media"
MEDIA_URL = env("MEDIA_URL", default="/media/")
