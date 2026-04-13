import os
import time
import hashlib
import logging
from typing import Any, Dict, Optional

import jwt
import requests
from django.http import JsonResponse
from django.http.response import HttpResponseRedirectBase
from django.contrib.auth import get_user_model
from django.utils import timezone
from xyn_orchestrator.models import UserIdentity, RoleBinding

logger = logging.getLogger(__name__)


def _auth_mode() -> str:
    return os.environ.get("XYN_AUTH_MODE", "simple").strip().lower()


class ApiTokenAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _extract_bearer_token(request)
        if token:
            expected = os.environ.get("XYN_UI_BEARER_TOKEN", os.environ.get("XYENCE_UI_BEARER_TOKEN", "")).strip()
            if expected and token == expected:
                request.user = _get_service_user()
                request._cached_user = request.user
                request._dont_enforce_csrf_checks = True
            else:
                claims = _verify_oidc_token(token) if _auth_mode() == "oidc" else None
                if claims:
                    identity = _get_or_create_identity_from_claims(claims)
                    user = _get_or_create_user_from_identity(identity) if identity else _get_or_create_user_from_claims(claims)
                    if user:
                        request.user = user
                        request._cached_user = user
                        request._dont_enforce_csrf_checks = True
                        if identity:
                            setattr(request, "_xyn_user_identity_id", str(identity.id))
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            identity_id = getattr(request, "session", {}).get("user_identity_id")
            if identity_id:
                identity = UserIdentity.objects.filter(id=identity_id).first()
                if identity:
                    user = _get_or_create_user_from_identity(identity)
                    if user:
                        request.user = user
                        request._cached_user = user
        response = self.get_response(request)
        if _is_workflow_api_unauth_redirect(request, response):
            return JsonResponse({"error": "not authenticated"}, status=401)
        return response


PREVIEW_SESSION_KEY = "xyn.preview.v1"
PREVIEW_TTL_SECONDS = 60 * 60
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PREVIEW_WRITE_ALLOWLIST = {
    "/xyn/api/preview/enable",
    "/xyn/api/preview/disable",
}


class PreviewModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, "session", None)
        if not session:
            return self.get_response(request)
        preview = session.get(PREVIEW_SESSION_KEY)
        if not isinstance(preview, dict):
            return self.get_response(request)
        if not bool(preview.get("enabled")):
            return self.get_response(request)
        expires_at = int(preview.get("expires_at") or 0)
        if expires_at <= int(time.time()):
            session.pop(PREVIEW_SESSION_KEY, None)
            session.modified = True
            return self.get_response(request)
        is_xyn_api_path = request.path.startswith("/xyn/api/") or request.path.startswith("/xyn/internal/")
        if is_xyn_api_path and request.method.upper() in UNSAFE_METHODS and request.path not in PREVIEW_WRITE_ALLOWLIST:
            return JsonResponse(
                {
                    "code": "PREVIEW_READ_ONLY",
                    "message": "Preview mode is read-only.",
                },
                status=403,
            )
        return self.get_response(request)


def _extract_bearer_token(request) -> str:
    header = request.headers.get("Authorization", "")
    if not header:
        return ""
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _get_service_user():
    User = get_user_model()
    username = os.environ.get("XYN_UI_BEARER_USER", os.environ.get("XYENCE_UI_BEARER_USER", "xyn-ui")).strip() or "xyn-ui"
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"is_staff": True, "is_active": True, "email": ""},
    )
    if created or not user.is_staff:
        user.is_staff = True
        user.is_active = True
        user.save(update_fields=["is_staff", "is_active"])
    return user


_JWKS_CLIENT: Optional[jwt.PyJWKClient] = None
_JWKS_CLIENT_TS: float = 0.0
_OIDC_DISCOVERY_CACHE: Dict[str, Dict[str, Any]] = {}
_OIDC_DISCOVERY_CACHE_TS: Dict[str, float] = {}
_OIDC_DISCOVERY_TTL_SECONDS = 3600.0


def _reset_oidc_caches_for_tests() -> None:
    global _JWKS_CLIENT, _JWKS_CLIENT_TS
    _JWKS_CLIENT = None
    _JWKS_CLIENT_TS = 0.0
    _OIDC_DISCOVERY_CACHE.clear()
    _OIDC_DISCOVERY_CACHE_TS.clear()


def _verify_oidc_token(token: str) -> Optional[Dict[str, Any]]:
    if _auth_mode() != "oidc":
        return None
    issuer = os.environ.get("OIDC_ISSUER", "https://accounts.google.com").strip()
    audience = os.environ.get("OIDC_CLIENT_ID", "").strip()
    if audience:
        try:
            jwk_client = _get_jwks_client(issuer)
            if jwk_client:
                signing_key = jwk_client.get_signing_key_from_jwt(token).key
                claims = jwt.decode(
                    token,
                    signing_key,
                    algorithms=["RS256"],
                    audience=audience,
                    issuer=issuer,
                    options={"verify_exp": True},
                )
                logger.info("oidc_jwks_authenticated issuer=%s", issuer)
                return claims
        except Exception as exc:
            logger.info("oidc_jwt_validation_failed_using_userinfo_fallback reason=%s", exc.__class__.__name__)
    return _verify_oidc_token_via_userinfo(token=token, issuer=issuer, audience=audience)


def _get_jwks_client(issuer: str) -> Optional[jwt.PyJWKClient]:
    global _JWKS_CLIENT, _JWKS_CLIENT_TS
    now = time.time()
    if _JWKS_CLIENT and now - _JWKS_CLIENT_TS < 3600:
        return _JWKS_CLIENT
    try:
        config = requests.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=10).json()
        jwks_uri = config.get("jwks_uri")
        if not jwks_uri:
            return None
        _JWKS_CLIENT = jwt.PyJWKClient(jwks_uri)
        _JWKS_CLIENT_TS = now
        return _JWKS_CLIENT
    except Exception:
        return None


def _oidc_discovery_doc(issuer: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    cached = _OIDC_DISCOVERY_CACHE.get(issuer)
    cached_at = _OIDC_DISCOVERY_CACHE_TS.get(issuer, 0.0)
    if cached and now - cached_at < _OIDC_DISCOVERY_TTL_SECONDS:
        return cached
    try:
        response = requests.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=5)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        _OIDC_DISCOVERY_CACHE[issuer] = payload
        _OIDC_DISCOVERY_CACHE_TS[issuer] = now
        return payload
    except Exception as exc:
        logger.warning("oidc_discovery_failed issuer=%s reason=%s", issuer, exc.__class__.__name__)
        return None


def _verify_oidc_token_via_userinfo(*, token: str, issuer: str, audience: str = "") -> Optional[Dict[str, Any]]:
    discovery = _oidc_discovery_doc(issuer)
    if not discovery:
        return None
    userinfo_endpoint = str(discovery.get("userinfo_endpoint") or "").strip()
    if not userinfo_endpoint:
        logger.info("oidc_userinfo_endpoint_missing issuer=%s", issuer)
        return None
    try:
        response = requests.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except Exception as exc:
        logger.warning("oidc_userinfo_request_failed issuer=%s reason=%s", issuer, exc.__class__.__name__)
        return None
    if response.status_code != 200:
        logger.info("oidc_userinfo_rejected issuer=%s status=%s", issuer, response.status_code)
        return None
    try:
        claims = response.json()
    except Exception:
        return None
    if not isinstance(claims, dict):
        return None
    claims = dict(claims)
    claims.setdefault("iss", issuer)
    if not str(claims.get("sub") or "").strip():
        return None
    aud = claims.get("aud")
    if audience and aud is not None:
        if isinstance(aud, str) and aud and aud != audience:
            logger.info("oidc_userinfo_audience_mismatch issuer=%s", issuer)
            return None
        if isinstance(aud, list) and aud and audience not in [str(item) for item in aud]:
            logger.info("oidc_userinfo_audience_mismatch issuer=%s", issuer)
            return None
    logger.info("oidc_userinfo_fallback_authenticated issuer=%s", issuer)
    return claims


def _get_or_create_user_from_claims(claims: Dict[str, Any]):
    email = (claims.get("email") or "").strip().lower()
    if not email:
        return None
    if claims.get("email_verified") is False:
        return None
    allowed = [d.strip().lower() for d in os.environ.get("OIDC_ALLOWED_DOMAINS", "xyence.io").split(",") if d.strip()]
    domain = email.split("@")[-1] if "@" in email else ""
    if allowed and domain not in allowed:
        return None
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=email,
        defaults={"email": email, "is_staff": True, "is_active": True},
    )
    if created or not user.is_staff:
        user.is_staff = True
        user.is_active = True
        user.email = email
        user.save(update_fields=["is_staff", "is_active", "email"])
    return user


def _get_or_create_identity_from_claims(claims: Dict[str, Any]) -> Optional[UserIdentity]:
    issuer = str(claims.get("iss") or os.environ.get("OIDC_ISSUER", "")).strip()
    subject = str(claims.get("sub") or "").strip()
    if not issuer or not subject:
        return None
    email = str(claims.get("email") or "").strip().lower()
    if claims.get("email_verified") is False:
        return None
    display_name = str(claims.get("name") or claims.get("preferred_username") or email or subject).strip()
    provider_id = str(claims.get("azp") or claims.get("aud") or "oidc").strip()
    if isinstance(claims.get("aud"), list):
        aud = claims.get("aud") or []
        provider_id = str(aud[0] if aud else provider_id).strip()
    identity = UserIdentity.objects.filter(issuer=issuer, subject=subject).first()
    if identity is None and email:
        identity = UserIdentity.objects.filter(email__iexact=email).order_by("-updated_at").first()
    if identity is None:
        identity = UserIdentity(
            provider="oidc",
            provider_id=provider_id,
            issuer=issuer,
            subject=subject,
        )
    identity.provider = "oidc"
    identity.provider_id = provider_id
    identity.issuer = issuer
    identity.subject = subject
    identity.email = email
    identity.display_name = display_name
    identity.claims_json = claims
    identity.last_login_at = timezone.now()
    identity.save()
    return identity


_WORKFLOW_API_PREFIXES = (
    "/xyn/api/applications",
    "/xyn/api/runs",
    "/xyn/api/runtime/runs",
    "/api/runs",
    "/api/runtime/runs",
)


def _is_workflow_api_unauth_redirect(request, response) -> bool:
    path = str(getattr(request, "path", "") or "")
    if not any(path.startswith(prefix) for prefix in _WORKFLOW_API_PREFIXES):
        return False
    if not isinstance(response, HttpResponseRedirectBase):
        return False
    location = str(getattr(response, "url", "") or response.headers.get("Location", "") or "")
    if not location:
        return False
    lower = location.lower()
    return "/accounts/login" in lower or "/auth/login" in lower


def _get_or_create_user_from_identity(identity: UserIdentity):
    User = get_user_model()
    issuer_hash = hashlib.sha256(identity.issuer.encode("utf-8")).hexdigest()[:12]
    username = f"oidc:{issuer_hash}:{identity.subject}"
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": identity.email or "", "is_staff": False, "is_active": True},
    )
    roles = RoleBinding.objects.filter(user_identity=identity).values_list("role", flat=True)
    role_set = set(roles)
    is_staff = bool(role_set.intersection({"platform_owner", "platform_admin", "platform_architect"}))
    changed = False
    if user.email != (identity.email or ""):
        user.email = identity.email or ""
        changed = True
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        changed = True
    if user.is_superuser:
        user.is_superuser = False
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if created or changed:
        user.save()
    return user
