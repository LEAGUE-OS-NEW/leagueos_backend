from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

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

RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="").strip()
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)


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
    "platform_admin",
    "authentication",
    "clubs",
    "dashboard",
    "discovery",
    "kyc",
    "fantasy",
    "markets",
    "notifications",
    "onboarding",
    "profiles",
    "sports",
    "system",
    "wallets",
    "news",
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

MARKET_MINIMUM_AGE = env.int("MARKET_MINIMUM_AGE", default=18)
MARKET_ALLOWED_COUNTRY_CODES = env.list("MARKET_ALLOWED_COUNTRY_CODES", default=[])
MARKET_KYC_PROVIDER = env("MARKET_KYC_PROVIDER", default="manual")
MARKET_KYC_WEBHOOK_SECRET = env("MARKET_KYC_WEBHOOK_SECRET", default="")
MARKET_KYC_WEBHOOK_TOLERANCE_SECONDS = env.int("MARKET_KYC_WEBHOOK_TOLERANCE_SECONDS", default=300)
MARKET_KYC_MAX_CALLBACK_BYTES = env.int("MARKET_KYC_MAX_CALLBACK_BYTES", default=65536)
MARKET_KYC_SESSION_HOURS = env.int("MARKET_KYC_SESSION_HOURS", default=24)
MARKET_BLOCKED_COUNTRY_CODES = env.list("MARKET_BLOCKED_COUNTRY_CODES", default=[])


def optional_non_negative_decimal(name):
    raw_value = env(name, default="").strip()
    if not raw_value:
        return None
    try:
        value = Decimal(raw_value)
    except InvalidOperation as error:
        raise ImproperlyConfigured(f"{name} must be a valid decimal number.") from error
    if not value.is_finite() or value < 0:
        raise ImproperlyConfigured(f"{name} must be a finite non-negative decimal number.")
    return value


MARKET_RESPONSIBLE_DEFAULT_MAX_ORDER_NOTIONAL = optional_non_negative_decimal(
    "MARKET_RESPONSIBLE_DEFAULT_MAX_ORDER_NOTIONAL"
)
MARKET_RESPONSIBLE_DEFAULT_DAILY_BUY_NOTIONAL = optional_non_negative_decimal(
    "MARKET_RESPONSIBLE_DEFAULT_DAILY_BUY_NOTIONAL"
)
MARKET_RESPONSIBLE_DEFAULT_WEEKLY_BUY_NOTIONAL = optional_non_negative_decimal(
    "MARKET_RESPONSIBLE_DEFAULT_WEEKLY_BUY_NOTIONAL"
)
MARKET_RESPONSIBLE_DEFAULT_MAX_OPEN_BUY_COMMITMENT = optional_non_negative_decimal(
    "MARKET_RESPONSIBLE_DEFAULT_MAX_OPEN_BUY_COMMITMENT"
)
MARKET_RESPONSIBLE_DEFAULT_MAX_MARKET_EXPOSURE = optional_non_negative_decimal(
    "MARKET_RESPONSIBLE_DEFAULT_MAX_MARKET_EXPOSURE"
)
MARKET_RESPONSIBLE_DEFAULT_MAX_TOTAL_EXPOSURE = optional_non_negative_decimal(
    "MARKET_RESPONSIBLE_DEFAULT_MAX_TOTAL_EXPOSURE"
)
MARKET_RESPONSIBLE_DEFAULT_MAX_CUMULATIVE_REALIZED_LOSS = optional_non_negative_decimal(
    "MARKET_RESPONSIBLE_DEFAULT_MAX_CUMULATIVE_REALIZED_LOSS"
)


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
        "RoleFf1Enum": [
            ("ADMIN", "Club Admin"),
            ("STAFF", "Club Staff"),
        ],
        "KYCVerificationStatusEnum": [
            ("NOT_STARTED", "Not Started"),
            ("PENDING", "Pending"),
            ("PROCESSING", "Processing"),
            ("VERIFIED", "Verified"),
            ("RETRY_REQUIRED", "Retry Required"),
            ("REJECTED", "Rejected"),
            ("REVIEW", "Review"),
            ("EXPIRED", "Expired"),
        ],
        "KYCVerificationAttemptStatusEnum": [
            ("PENDING", "Pending"),
            ("PROCESSING", "Processing"),
            ("COMPLETED", "Completed"),
            ("FAILED", "Failed"),
            ("CANCELLED", "Cancelled"),
        ],
        "KYCCheckResultStatusEnum": [
            ("NOT_RUN", "Not Run"),
            ("PROCESSING", "Processing"),
            ("PASSED", "Passed"),
            ("FAILED", "Failed"),
            ("UNCERTAIN", "Uncertain"),
            ("NOT_APPLICABLE", "Not Applicable"),
        ],
        "Status272Enum": [
            ("CREATED", "Created"),
            ("PENDING", "Pending"),
            ("IN_REVIEW", "In review"),
            ("VERIFIED", "Verified"),
            ("REJECTED", "Rejected"),
            ("EXPIRED", "Expired"),
            ("CANCELLED", "Cancelled"),
            ("ERROR", "Error"),
        ],
        "ComplianceDecisionStatusEnum": [
            ("PENDING", "Pending"),
            ("APPROVED", "Approved"),
            ("REJECTED", "Rejected"),
        ],
        "ComplianceDecisionTypeEnum": [
            ("CLEAR_CRITICAL_RISK_BLOCK", "Clear critical risk block"),
            ("REMOVE_SUSPENDED_RESTRICTION", "Remove suspension"),
            ("JURISDICTION_BLOCK_TO_ALLOW", "Allow jurisdiction"),
            ("APPLY_RISK_OVERRIDE", "Apply risk override"),
            ("CLEAR_RISK_OVERRIDE", "Clear risk override"),
        ],
        "MarketDisputeDecisionTypeEnum": [
            ("CONFIRM", "Confirm provisional result"),
            ("CORRECT", "Correct provisional result"),
            ("VOID", "Void market"),
            ("EXTEND_REVIEW", "Extend review"),
        ],
        "RiskBandEnum": [
            ("LOW", "Low"),
            ("MEDIUM", "Medium"),
            ("HIGH", "High"),
            ("CRITICAL", "Critical"),
        ],
        "ResponsibleParticipationEventTypeEnum": [
            ("LIMITS_SET", "Limits set"),
            ("LIMITS_TIGHTENED", "Limits tightened"),
            ("ADMIN_LIMITS_UPDATED", "Admin limits updated"),
            ("ADMIN_CONTROLS_UPDATED", "Admin controls updated"),
            ("COOLING_OFF_STARTED", "Cooling off started"),
            ("COOLING_OFF_EXTENDED", "Cooling off extended"),
            ("SELF_EXCLUSION_STARTED", "Self exclusion started"),
            ("SELF_EXCLUSION_EXTENDED", "Self exclusion extended"),
            ("ADMIN_BLOCK_STARTED", "Admin block started"),
            ("ADMIN_BLOCK_EXTENDED", "Admin block extended"),
        ],
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
            ("RESOLVE", "Resolve"),
            ("VOID", "Void"),
        ],
        "MarketOutcomeSideEnum": [
            ("YES", "Yes"),
            ("NO", "No"),
        ],
        "MarketEventStatusEnum": [
            ("DRAFT", "Draft"),
            ("PUBLISHED", "Published"),
            ("ARCHIVED", "Archived"),
        ],
        "MarketEventTypeEnum": [
            ("SPORTING_EVENT", "Sporting event"),
            ("LEAGUE_EVENT", "League event"),
            ("GENERAL_EVENT", "General event"),
        ],
        "MarketProposalStatusEnum": [
            ("SUBMITTED", "Submitted"),
            ("UNDER_REVIEW", "Under review"),
            ("APPROVED", "Approved"),
            ("REJECTED", "Rejected"),
            ("DUPLICATE", "Duplicate"),
            ("WITHDRAWN", "Withdrawn"),
        ],
        "MarketProposalDuplicateStatusEnum": [
            ("CLEAR", "Clear"),
            ("POSSIBLE_DUPLICATE", "Possible duplicate"),
            ("CONFIRMED_DUPLICATE", "Confirmed duplicate"),
        ],
        "MarketProposalReviewActionEnum": [
            ("START_REVIEW", "Start review"),
            ("APPROVE", "Approve"),
            ("REJECT", "Reject"),
            ("MARK_DUPLICATE", "Mark duplicate"),
        ],
        "SportingEventStatusEnum": [
            ("DRAFT", "Draft"),
            ("SCHEDULED", "Scheduled"),
            ("LIVE", "Live"),
            ("COMPLETED", "Completed"),
            ("POSTPONED", "Postponed"),
            ("CANCELLED", "Cancelled"),
            ("ABANDONED", "Abandoned"),
        ],
        "SportingEventTypeEnum": [
            ("MATCH", "Match"),
            ("RACE", "Race"),
            ("TOURNAMENT", "Tournament"),
            ("BOUT", "Bout"),
            ("SERIES", "Series"),
            ("OTHER", "Other"),
        ],
        "MarketOrderSideEnum": [
            ("BUY", "Buy"),
            ("SELL", "Sell"),
        ],
    },
}

SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"].update(
    {
        "LedgerAccountTypeEnum": [
            ("USER_WALLET", "User Wallet"),
            ("PROVIDER_PAYABLE", "Provider Payable"),
            ("REVENUE", "Revenue"),
        ],
        "ClubContentStatusEnum": [
            ("DRAFT", "Draft"),
            ("PENDING_APPROVAL", "Pending approval"),
            ("APPROVED", "Approved"),
            ("PUBLISHED", "Published"),
            ("REJECTED", "Rejected"),
            ("ARCHIVED", "Archived"),
        ],
        "Status7b4Enum": [
            ("DRAFT", "Draft"),
            ("PENDING_APPROVAL", "Pending approval"),
            ("PUBLISHED", "Published"),
            ("ARCHIVED", "Archived"),
        ],
    }
)


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
REGISTRATION_OTP_CHANNEL = env("REGISTRATION_OTP_CHANNEL", default="EMAIL").upper()
SMS_OTP_ENABLED = env.bool("SMS_OTP_ENABLED", default=False)
OTP_RESEND_COOLDOWN_MINUTES = env.int("OTP_RESEND_COOLDOWN_MINUTES", default=2)
OTP_MAX_DAILY_RESENDS = env.int("OTP_MAX_DAILY_RESENDS", default=5)
OTP_MAX_VERIFICATION_ATTEMPTS = env.int("OTP_MAX_VERIFICATION_ATTEMPTS", default=5)
OTP_VERIFICATION_LOCK_MINUTES = env.int("OTP_VERIFICATION_LOCK_MINUTES", default=15)
OTP_EXPIRY_MINUTES = env.int("OTP_EXPIRY_MINUTES", default=10)

if REGISTRATION_OTP_CHANNEL != "EMAIL" and not SMS_OTP_ENABLED:
    raise ImproperlyConfigured(
        "REGISTRATION_OTP_CHANNEL must be EMAIL while SMS_OTP_ENABLED is false."
    )

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

# =============================================================================
# Automated KYC & Identity Verification Settings
# =============================================================================
KYC_ENABLED = env.bool("KYC_ENABLED", default=True)
KYC_MAX_ATTEMPTS = env.int("KYC_MAX_ATTEMPTS", default=3)
KYC_MAX_DOCUMENT_SIZE_MB = env.int("KYC_MAX_DOCUMENT_SIZE_MB", default=10)
KYC_MIN_IMAGE_DIMENSION = env.int("KYC_MIN_IMAGE_DIMENSION", default=300)
KYC_MAX_IMAGE_DIMENSION = env.int("KYC_MAX_IMAGE_DIMENSION", default=6000)
KYC_FACE_MATCH_PASS_THRESHOLD = env.float("KYC_FACE_MATCH_PASS_THRESHOLD", default=0.70)
KYC_FACE_MATCH_REVIEW_THRESHOLD = env.float("KYC_FACE_MATCH_REVIEW_THRESHOLD", default=0.50)
KYC_RISK_REVIEW_THRESHOLD = env.float("KYC_RISK_REVIEW_THRESHOLD", default=0.40)
KYC_RISK_REJECT_THRESHOLD = env.float("KYC_RISK_REJECT_THRESHOLD", default=0.75)
KYC_DOCUMENT_RETENTION_DAYS = env.int("KYC_DOCUMENT_RETENTION_DAYS", default=30)
KYC_SELFIE_RETENTION_DAYS = env.int("KYC_SELFIE_RETENTION_DAYS", default=30)
KYC_PROCESSING_MODE = env("KYC_PROCESSING_MODE", default="internal")

# =============================================================================
# Celery / Redis Settings
# =============================================================================
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

# =============================================================================
# Cache Settings
# =============================================================================
try:
    import redis

    redis.StrictRedis.from_url(env("REDIS_URL", default="redis://redis:6379/1")).ping()
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("REDIS_URL", default="redis://redis:6379/1"),
        }
    }
except Exception:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-snowflake",
        }
    }
