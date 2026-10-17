import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from ninja.security import HttpBearer

logger = logging.getLogger(__name__)
User = get_user_model()

JWT_ALGORITHM = getattr(settings, "JWT_ALGORITHM", "HS256")
JWT_EXP_DAYS = getattr(settings, "JWT_EXP_DAYS", 7)


def generate_access_token(user: Any) -> str:
    """Generate a signed, stateless JWT access token for the given user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.pk),
        "email": user.email,
        "iat": now,
        "exp": now + timedelta(days=JWT_EXP_DAYS),
        "type": "access",
    }
    secret_key = getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY)
    token = jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)
    return token


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT access token."""
    secret_key = getattr(settings, "JWT_SECRET_KEY", settings.SECRET_KEY)
    try:
        payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            logger.warning("JWT validation failed: Invalid token type %s", payload.get("type"))
            return None
        return payload
    except jwt.ExpiredSignatureError:
        logger.info("JWT validation failed: Token has expired")
        return None
    except jwt.InvalidTokenError as err:
        logger.warning("JWT validation failed: %s", err)
        return None


_USER_CACHE: Dict[int, Any] = {}
_USER_CACHE_TTL = 300  # 5 minutes


class JWTAuth(HttpBearer):
    """
    Custom Django Ninja Bearer token security scheme.
    Extracts Bearer token from the 'Authorization' header, validates the JWT,
    and sets request.auth to the active authenticated User instance.
    Cached in memory to eliminate cross-continent round-trip latency on every API hit.
    """

    def authenticate(self, request, token: str) -> Optional[Any]:
        payload = decode_access_token(token)
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        now = datetime.now(timezone.utc).timestamp()
        try:
            uid_int = int(user_id)
            if uid_int in _USER_CACHE:
                cached_user, cache_time = _USER_CACHE[uid_int]
                if (now - cache_time) < _USER_CACHE_TTL:
                    return cached_user
        except (ValueError, TypeError):
            pass

        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user:
            # Auto-backup Super Admin status from .env setting
            super_admin_emails = getattr(settings, "SUPER_ADMIN_EMAILS", [])
            save_fields = []
            if user.email and user.email.lower() in super_admin_emails:
                if user.admin_role != "SUPER_ADMIN" or not user.is_staff or not user.is_superuser:
                    user.admin_role = "SUPER_ADMIN"
                    user.is_staff = True
                    user.is_superuser = True
                    save_fields.extend(["admin_role", "is_staff", "is_superuser"])

            # Track activity timestamp (throttled to 1 hr to avoid high SQL load)
            from django.utils import timezone as django_tz
            if not user.last_login or (django_tz.now() - user.last_login).total_seconds() > 3600:
                user.last_login = django_tz.now()
                save_fields.append("last_login")

            if save_fields:
                user.save(update_fields=list(set(save_fields)))

            try:
                _USER_CACHE[int(user_id)] = (user, now)
            except (ValueError, TypeError):
                pass
        return user


def verify_google_id_token(id_token_str: str) -> Dict[str, Any]:
    """
    Verifies a Google OAuth2 ID token using the official Google Auth library.
    Ensures the token audience matches GOOGLE_CLIENT_ID and has not expired.
    """
    google_client_id = getattr(settings, "GOOGLE_CLIENT_ID", None)
    if not google_client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not configured in Django settings.")

    try:
        request_obj = google_requests.Request()
        payload = google_id_token.verify_oauth2_token(
            id_token_str,
            request_obj,
            google_client_id,
        )
        return payload
    except Exception as err:
        logger.error("Google ID Token verification failed: %s", err, exc_info=True)
        raise ValueError(f"Invalid Google ID token: {err}") from err


def provision_google_user(payload: Dict[str, Any]) -> Any:
    """
    Finds or creates a User from verified Google ID token payload.
    Synchronizes profile metadata (name, avatar) if updated.
    Auto-promotes to SUPER_ADMIN if email is configured in SUPER_ADMIN_EMAILS.
    """
    email = payload.get("email")
    if not email:
        raise ValueError("Google token payload does not contain an email address.")

    normalized_email = email.lower().strip()
    first_name = payload.get("given_name", "") or ""
    last_name = payload.get("family_name", "") or ""
    avatar_url = payload.get("picture", "") or ""

    super_admin_emails = getattr(settings, "SUPER_ADMIN_EMAILS", [])
    is_super = normalized_email in super_admin_emails

    from django.utils import timezone as django_tz

    user, created = User.objects.get_or_create(
        email=normalized_email,
        defaults={
            "first_name": first_name,
            "last_name": last_name,
            "avatar_url": avatar_url,
            "is_active": True,
            "admin_role": "SUPER_ADMIN" if is_super else "NONE",
            "is_staff": is_super,
            "is_superuser": is_super,
            "last_login": django_tz.now(),
        },
    )

    updates = ["last_login"]
    user.last_login = django_tz.now()
    if not created:
        # Sync latest profile changes
        if avatar_url and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            updates.append("avatar_url")
        if first_name and not user.first_name:
            user.first_name = first_name
            updates.append("first_name")
        if last_name and not user.last_name:
            user.last_name = last_name
            updates.append("last_name")

    # Always ensure .env super admin protection
    if is_super and (user.admin_role != "SUPER_ADMIN" or not user.is_staff or not user.is_superuser):
        user.admin_role = "SUPER_ADMIN"
        user.is_staff = True
        user.is_superuser = True
        updates.extend(["admin_role", "is_staff", "is_superuser"])

    if updates:
        user.save(update_fields=list(set(updates)))

    # Auto-link any tour memberships assigned to this email
    try:
        from apps.tours.models import TourMember
        TourMember.objects.filter(email__iexact=normalized_email, user__isnull=True).update(user=user)
    except Exception:
        pass

    return user

