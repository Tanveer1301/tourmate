import logging
import sys
import time
from collections import defaultdict
from typing import Dict, List

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# In-memory sliding window store: IP -> List of timestamps
_RATE_LIMIT_STORE: Dict[str, List[float]] = defaultdict(list)
_LAST_CLEANUP: float = time.time()


def get_client_ip(request) -> str:
    """Safely extract client IP from X-Forwarded-For or REMOTE_ADDR."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "127.0.0.1")
    return ip or "127.0.0.1"


class SecurityRateLimitMiddleware:
    """
    Lightweight, high-performance sliding window rate limiter.
    Protects TourMate database and APIs from:
    1. Automated brute-force attacks on auth endpoints
    2. DDoS / rapid flooding of database write queries (POST, PUT, DELETE)
    3. Malicious scraping & API abuse
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Skip rate limiting in unit test suite or when disabled
        if ("test" in sys.argv and not getattr(settings, "ENABLE_RATE_LIMIT_IN_TESTS", False)) or getattr(settings, "DISABLE_RATE_LIMIT", False):
            return self.get_response(request)

        path = request.path_info or ""

        # 2. Only rate limit API endpoints
        if not path.startswith("/api/"):
            return self.get_response(request)

        # 3. Determine bucket & limit
        now = time.time()
        ip = get_client_ip(request)
        method = request.method.upper()

        if path.startswith("/api/v1/auth/"):
            bucket = f"auth:{ip}"
            limit = 30  # Max 30 auth attempts per minute
            window = 60
        elif method in ("POST", "PUT", "DELETE", "PATCH"):
            bucket = f"write:{ip}"
            limit = 60  # Max 60 writes per minute
            window = 60
        else:
            bucket = f"read:{ip}"
            limit = 180  # Max 180 reads per minute
            window = 60

        # Periodic cleanup of expired entries every 5 minutes
        global _LAST_CLEANUP
        if now - _LAST_CLEANUP > 300:
            _LAST_CLEANUP = now
            expired_keys = []
            for k, timestamps in list(_RATE_LIMIT_STORE.items()):
                valid = [t for t in timestamps if now - t < 120]
                if valid:
                    _RATE_LIMIT_STORE[k] = valid
                else:
                    expired_keys.append(k)
            for k in expired_keys:
                _RATE_LIMIT_STORE.pop(k, None)

        # Sliding window check
        timestamps = _RATE_LIMIT_STORE[bucket]
        recent = [t for t in timestamps if now - t < window]

        if len(recent) >= limit:
            logger.warning("Rate limit exceeded for %s on %s %s", ip, method, path)
            resp = JsonResponse(
                {
                    "detail": "Too many requests. For platform security, please slow down and try again.",
                    "code": "RATE_LIMIT_EXCEEDED",
                },
                status=429,
            )
            resp["Retry-After"] = str(window)
            return resp

        recent.append(now)
        _RATE_LIMIT_STORE[bucket] = recent

        return self.get_response(request)
