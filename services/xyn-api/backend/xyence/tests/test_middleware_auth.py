from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.http import JsonResponse
from django.shortcuts import redirect
from django.test import RequestFactory, TestCase

from xyence.middleware import ApiTokenAuthMiddleware, _reset_oidc_caches_for_tests
from xyn_orchestrator.models import UserIdentity


def _with_session(request):
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()
    return request


class ApiTokenAuthMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        _reset_oidc_caches_for_tests()

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc", "OIDC_ISSUER": "https://issuer.example.com", "OIDC_CLIENT_ID": "xyn-ui"}, clear=False)
    @mock.patch("xyence.middleware.jwt.decode")
    @mock.patch("xyence.middleware._get_jwks_client")
    def test_valid_jwt_bearer_authenticates(self, mock_jwks_client: mock.Mock, mock_jwt_decode: mock.Mock):
        key = mock.Mock()
        key.key = "signing-key"
        mock_jwks_client.return_value = mock.Mock(get_signing_key_from_jwt=mock.Mock(return_value=key))
        mock_jwt_decode.return_value = {
            "iss": "https://issuer.example.com",
            "sub": "subject-jwt",
            "email": "jwt-user@example.com",
            "name": "JWT User",
            "aud": "xyn-ui",
        }

        request = _with_session(self.factory.get("/xyn/api/applications", HTTP_AUTHORIZATION="Bearer token-ok"))
        middleware = ApiTokenAuthMiddleware(
            lambda req: JsonResponse(
                {
                    "authenticated": bool(getattr(req, "user", None) and req.user.is_authenticated),
                    "identity_bound": bool(str(getattr(req, "_xyn_user_identity_id", "") or "").strip()),
                }
            )
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("authenticated"))
        self.assertTrue(response.json().get("identity_bound"))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc", "OIDC_ISSUER": "https://issuer.example.com", "OIDC_CLIENT_ID": "xyn-ui"}, clear=False)
    @mock.patch("xyence.middleware.jwt.decode", side_effect=Exception("bad_jwt"))
    @mock.patch("xyence.middleware._get_jwks_client")
    @mock.patch("xyence.middleware.requests.get")
    def test_userinfo_fallback_authenticates_when_jwt_decode_fails(
        self,
        mock_requests_get: mock.Mock,
        mock_jwks_client: mock.Mock,
        _mock_jwt_decode: mock.Mock,
    ):
        key = mock.Mock()
        key.key = "signing-key"
        mock_jwks_client.return_value = mock.Mock(get_signing_key_from_jwt=mock.Mock(return_value=key))
        discovery_response = mock.Mock()
        discovery_response.status_code = 200
        discovery_response.raise_for_status.return_value = None
        discovery_response.json.return_value = {"userinfo_endpoint": "https://issuer.example.com/userinfo"}
        userinfo_response = mock.Mock()
        userinfo_response.status_code = 200
        userinfo_response.json.return_value = {
            "sub": "userinfo-subject",
            "email": "userinfo@example.com",
            "name": "Userinfo User",
        }
        mock_requests_get.side_effect = [discovery_response, userinfo_response]

        request = _with_session(self.factory.get("/xyn/api/applications", HTTP_AUTHORIZATION="Bearer token-ok"))
        middleware = ApiTokenAuthMiddleware(
            lambda req: JsonResponse(
                {
                    "authenticated": bool(getattr(req, "user", None) and req.user.is_authenticated),
                    "identity_bound": bool(str(getattr(req, "_xyn_user_identity_id", "") or "").strip()),
                }
            )
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("authenticated"))
        self.assertTrue(response.json().get("identity_bound"))
        identity = UserIdentity.objects.filter(subject="userinfo-subject", issuer="https://issuer.example.com").first()
        self.assertIsNotNone(identity)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc", "OIDC_ISSUER": "https://issuer.example.com", "OIDC_CLIENT_ID": "xyn-ui"}, clear=False)
    @mock.patch("xyence.middleware.jwt.decode", side_effect=Exception("bad_jwt"))
    @mock.patch("xyence.middleware._get_jwks_client")
    @mock.patch("xyence.middleware.requests.get")
    def test_when_jwt_and_userinfo_fail_workflow_api_returns_json_401(
        self,
        mock_requests_get: mock.Mock,
        mock_jwks_client: mock.Mock,
        _mock_jwt_decode: mock.Mock,
    ):
        key = mock.Mock()
        key.key = "signing-key"
        mock_jwks_client.return_value = mock.Mock(get_signing_key_from_jwt=mock.Mock(return_value=key))
        discovery_response = mock.Mock()
        discovery_response.status_code = 200
        discovery_response.raise_for_status.return_value = None
        discovery_response.json.return_value = {"userinfo_endpoint": "https://issuer.example.com/userinfo"}
        userinfo_response = mock.Mock()
        userinfo_response.status_code = 401
        userinfo_response.json.return_value = {"error": "unauthorized"}
        mock_requests_get.side_effect = [discovery_response, userinfo_response]

        request = _with_session(self.factory.get("/xyn/api/applications", HTTP_AUTHORIZATION="Bearer bad-token"))
        middleware = ApiTokenAuthMiddleware(lambda _req: redirect("/accounts/login/?next=/xyn/api/applications"))
        response = middleware(request)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.has_header("Location"))
        self.assertEqual(response.json().get("error"), "not authenticated")

    @mock.patch.dict("os.environ", {"XYN_UI_BEARER_TOKEN": "service-token-123", "XYN_UI_BEARER_USER": "xyn-mcp"}, clear=False)
    def test_service_bearer_sets_user_and_identity(self):
        request = _with_session(
            self.factory.get(
                "/xyn/api/applications",
                HTTP_AUTHORIZATION="Bearer service-token-123",
            )
        )
        middleware = ApiTokenAuthMiddleware(
            lambda req: JsonResponse(
                {
                    "authenticated": bool(getattr(req, "user", None) and req.user.is_authenticated),
                    "identity_bound": bool(str(getattr(req, "_xyn_user_identity_id", "") or "").strip()),
                }
            )
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("authenticated"))
        self.assertTrue(response.json().get("identity_bound"))
