from django.contrib.auth import get_user_model
from ninja import Router
from ninja.errors import HttpError

from apps.accounts.security import (
    JWTAuth,
    generate_access_token,
    provision_google_user,
    verify_google_id_token,
)
from apps.tours.schemas import AuthTokenOut, ErrorOut, GoogleAuthIn, ProfileUpdateIn, UserOut

User = get_user_model()
router = Router(tags=["Authentication"])



@router.post(
    "/google",
    response={200: AuthTokenOut, 400: ErrorOut},
    auth=None,
    summary="Exchange Google ID Token for JWT Access Token",
)
def google_token_exchange(request, payload: GoogleAuthIn):
    """
    Exchanges a Google OAuth2 id_token from mobile or web client for a stateless
    TourMate JWT access token. Automatically provisions the user if they are signing in
    for the first time.
    """
    try:
        google_payload = verify_google_id_token(payload.id_token)
    except ValueError as err:
        raise HttpError(400, str(err))

    user = provision_google_user(google_payload)
    access_token = generate_access_token(user)

    return 200, {
        "access_token": access_token,
        "token_type": "Bearer",
        "user": user,
    }


@router.post(
    "/demo",
    response={200: AuthTokenOut},
    auth=None,
    summary="Instant demo login as Alex Rivers (Tour Owner)",
)
def demo_login(request):
    """
    Convenience endpoint for instant preview & testing without requiring Google OAuth credentials.
    Demo user Alex Rivers is strictly a regular tour organizer with ZERO admin or staff privileges.
    """
    from django.utils import timezone as django_tz

    user, _ = User.objects.get_or_create(
        email="alex@tourmate.test",
        defaults={
            "first_name": "Alex",
            "last_name": "Rivers",
            "is_staff": False,
            "is_superuser": False,
            "admin_role": "NONE",
        },
    )
    updates = []
    if user.is_staff:
        user.is_staff = False
        updates.append("is_staff")
    if user.is_superuser:
        user.is_superuser = False
        updates.append("is_superuser")
    if user.admin_role != "NONE":
        user.admin_role = "NONE"
        updates.append("admin_role")
    user.last_login = django_tz.now()
    updates.append("last_login")

    user.save(update_fields=updates)
    access_token = generate_access_token(user)

    return 200, {
        "access_token": access_token,
        "token_type": "Bearer",
        "user": user,
    }


@router.put(
    "/profile",
    response={200: UserOut, 400: ErrorOut},
    auth=JWTAuth(),
    summary="Update authenticated user profile",
)
def update_profile(request, payload: ProfileUpdateIn):
    user = request.auth
    if not user:
        raise HttpError(401, "Authentication required.")

    if getattr(user, "email", None) == "alex@tourmate.test":
        raise HttpError(403, "ডেমো অ্যাকাউন্টে নাম পরিবর্তন করা যাবে না (Demo account profile name is locked).")

    updates = []
    if payload.name is not None:
        clean_name = payload.name.strip()
        if clean_name:
            parts = clean_name.split(maxsplit=1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ""
        else:
            user.first_name = ""
            user.last_name = ""
        updates.extend(["first_name", "last_name"])
    else:
        if payload.first_name is not None:
            user.first_name = payload.first_name.strip()
            updates.append("first_name")
        if payload.last_name is not None:
            user.last_name = payload.last_name.strip()
            updates.append("last_name")

    if updates:
        user.save(update_fields=list(set(updates)))

    return 200, user
