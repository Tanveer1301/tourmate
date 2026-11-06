import time
from decimal import Decimal
from django.test import TestCase, override_settings
from django.core.exceptions import DisallowedHost
import jwt

from apps.accounts.models import AdminRole, User
from apps.accounts.security import generate_access_token
from apps.tours.models import Tour, TourMember


class SecurityHardeningTestCase(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            email="user_a@tourmate.test",
            first_name="Alice",
            last_name="Owner",
        )
        self.token_a = generate_access_token(self.user_a)

        self.user_b = User.objects.create_user(
            email="user_b@tourmate.test",
            first_name="Bob",
            last_name="Hacker",
        )
        self.token_b = generate_access_token(self.user_b)

        # Alice's private tour
        self.tour_a = Tour.objects.create(
            title="Alice Private Tour",
            created_by=self.user_a,
        )
        TourMember.objects.create(
            tour=self.tour_a,
            user=self.user_a,
            name="Alice",
            role=TourMember.Role.OWNER,
        )

    def test_security_headers_present(self):
        """Verify essential security headers (X-Frame-Options, X-Content-Type-Options) are enforced."""
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")

    def test_host_header_injection_blocked(self):
        """Verify that requests with unauthorized/malicious Host headers are rejected with 400 Bad Request."""
        resp = self.client.get("/login", HTTP_HOST="evil-attacker.com")
        self.assertEqual(resp.status_code, 400)

    def test_idor_cross_tour_protection(self):
        """Verify that User B cannot access, read dashboard, or modify User A's private tour."""
        # 1. User B tries to view Alice's tour dashboard -> 403 Forbidden
        resp_view = self.client.get(
            f"/api/v1/tours/{self.tour_a.id}/dashboard",
            HTTP_AUTHORIZATION=f"Bearer {self.token_b}",
        )
        self.assertEqual(resp_view.status_code, 403)

        # 2. User B tries to delete Alice's tour -> 403 Forbidden
        resp_del = self.client.delete(
            f"/api/v1/tours/{self.tour_a.id}",
            HTTP_AUTHORIZATION=f"Bearer {self.token_b}",
        )
        self.assertEqual(resp_del.status_code, 403)
        self.assertTrue(Tour.objects.filter(id=self.tour_a.id).exists())

        # 3. User B tries to add expense on Alice's tour -> 403 Forbidden
        resp_exp = self.client.post(
            f"/api/v1/tours/{self.tour_a.id}/expenses",
            data={"purpose": "Malicious Expense", "amount": "1000.00"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token_b}",
        )
        self.assertEqual(resp_exp.status_code, 403)

    def test_tampered_jwt_signature_rejected(self):
        """Verify that an attacker attempting to forge a JWT signature is rejected with 401."""
        tampered_token = jwt.encode(
            {"sub": str(self.user_a.id), "email": self.user_a.email, "type": "access", "exp": 9999999999, "iat": 1000000000},
            "completely-wrong-attacker-secret-key-that-does-not-match",
            algorithm="HS256",
        )
        resp = self.client.get(
            "/api/v1/tours/",
            HTTP_AUTHORIZATION=f"Bearer {tampered_token}",
        )
        self.assertEqual(resp.status_code, 401)

    def test_jwt_missing_required_claims_rejected(self):
        """Verify that JWT tokens lacking 'sub', 'exp', or 'iat' claims are rejected."""
        from django.conf import settings
        secret = getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY)
        incomplete_token = jwt.encode(
            {"email": "nobody@test.com", "type": "access"},  # missing sub, exp, iat
            secret,
            algorithm="HS256",
        )
        resp = self.client.get(
            "/api/v1/tours/",
            HTTP_AUTHORIZATION=f"Bearer {incomplete_token}",
        )
        self.assertEqual(resp.status_code, 401)

    def test_blocked_admin_cannot_access_admin_console(self):
        """Verify that a blocked admin user (is_active=False) cannot access admin endpoints."""
        blocked_admin = User.objects.create_user(
            email="blocked_subadmin@tourmate.test",
            first_name="Blocked",
            last_name="Admin",
            admin_role=AdminRole.SUB_ADMIN,
            is_active=False,
            is_staff=True,
        )
        token = generate_access_token(blocked_admin)

        resp = self.client.get(
            "/api/v1/admin/me",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("ব্লক", resp.json().get("detail", ""))

    def test_rate_limit_middleware_throttles_rapid_requests(self):
        """Verify that SecurityRateLimitMiddleware returns 429 when threshold is exceeded."""
        from apps.web.middleware import _RATE_LIMIT_STORE
        _RATE_LIMIT_STORE.clear()

        with override_settings(ENABLE_RATE_LIMIT_IN_TESTS=True):
            # Simulate 30 rapid requests to an auth endpoint
            for _ in range(30):
                resp = self.client.post("/api/v1/auth/demo")
                self.assertEqual(resp.status_code, 200)

            # 31st request should be throttled
            resp_throttled = self.client.post("/api/v1/auth/demo")
            self.assertEqual(resp_throttled.status_code, 429)
            self.assertEqual(resp_throttled.json().get("code"), "RATE_LIMIT_EXCEEDED")
            self.assertTrue(resp_throttled.has_header("Retry-After"))

