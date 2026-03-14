import os
from pathlib import Path
from urllib.parse import urlsplit

from .runtime_env import bootstrap_runtime_env

bootstrap_runtime_env()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = False

ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]
if "*" not in ALLOWED_HOSTS and "backend" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("backend")
if "*" not in ALLOWED_HOSTS and ".xyence.io" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".xyence.io")

# Respect proxy headers from ingress/proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.postgres",
    "rest_framework",
    "corsheaders",
    "django_ckeditor_5",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "xyn_orchestrator.apps.XynOrchestratorConfig",
    "web",
]

MIDDLEWARE = [
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "xyence.middleware.ApiTokenAuthMiddleware",
    "xyence.middleware.PreviewModeMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "xyence.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "xyence.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "xyence"),
        "USER": os.environ.get("POSTGRES_USER", "xyence"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "xyence"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

SITE_ID = int(os.environ.get("DJANGO_SITE_ID", "1"))

ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_EMAIL_VERIFICATION = "optional"
_public_base_url = str(os.environ.get("XYN_PUBLIC_BASE_URL", "http://localhost")).strip() or "http://localhost"
_public_scheme = (urlsplit(_public_base_url).scheme or "http").lower()
_is_localhost_public = (urlsplit(_public_base_url).hostname or "").lower() in {"localhost", "127.0.0.1"}
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https" if _public_scheme == "https" else "http"
ACCOUNT_ALLOWED_EMAIL_DOMAINS = [
    domain.strip()
    for domain in os.environ.get("ALLOWED_LOGIN_DOMAINS", "xyence.io").split(",")
    if domain.strip()
]
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = "/"

SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_ADAPTER = "xyence.adapters.DomainRestrictedSocialAccountAdapter"

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# Localhost OIDC must avoid Secure cookies on plain HTTP and must not set cookie domains.
_cookie_secure_default = _public_scheme == "https" and not _is_localhost_public
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true" if _cookie_secure_default else "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "true" if _cookie_secure_default else "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_default_samesite = "None" if SESSION_COOKIE_SECURE else "Lax"
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", _default_samesite).strip() or _default_samesite
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", _default_samesite).strip() or _default_samesite
_base_domain = os.environ.get("XYN_BASE_DOMAIN", "").strip()
_default_cookie_domain = ""
if _base_domain and _base_domain not in {"localhost", "127.0.0.1"}:
    _default_cookie_domain = f".{_base_domain}"
SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN", _default_cookie_domain).strip() or None
CSRF_COOKIE_DOMAIN = os.environ.get("CSRF_COOKIE_DOMAIN", SESSION_COOKIE_DOMAIN or "").strip() or None

_redis_session_url = str(os.environ.get("REDIS_URL", "redis://redis:6379/0")).strip()
if _redis_session_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _redis_session_url,
        }
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("XYN_ARTIFACT_ROOT") or os.environ.get("XYN_MEDIA_ROOT") or (BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ]
}

CKEDITOR_5_CONFIGS = {
    "default": {
        "toolbar": {
            "items": [
                "heading",
                "|",
                "bold",
                "italic",
                "link",
                "bulletedList",
                "numberedList",
                "blockQuote",
                "|",
                "insertTable",
                "imageUpload",
                "codeBlock",
                "|",
                "undo",
                "redo",
            ],
        },
        "codeBlock": {
            "languages": [
                {"language": "plaintext", "label": "Plain text"},
                {"language": "mermaid", "label": "Mermaid"},
            ],
        },
    }
}

CKEDITOR_5_FILE_UPLOAD_PERMISSION = "authenticated"
