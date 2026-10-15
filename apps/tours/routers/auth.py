from django.contrib.auth import get_user_model
from ninja import Router
from ninja.errors import HttpError

from apps.accounts.security import (
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
    """
    user, _ = User.objects.get_or_create(
        email="alex@tourmate.test",
        defaults={
            "first_name": "Alex",
            "last_name": "Rivers",
            "is_staff": True,
        },
    )
    access_token = generate_access_token(user)

    return 200, {
        "access_token": access_token,
        "token_type": "Bearer",
        "user": user,
    }


@router.put(
    "/profile",
    response={200: UserOut, 400: ErrorOut},
    summary="Update authenticated user profile",
)
def update_profile(request, payload: ProfileUpdateIn):
    user = request.auth
    if not user:
        raise HttpError(401, "Authentication required.")

    updates = []
    if payload.first_name is not None:
        user.first_name = payload.first_name.strip()
        updates.append("first_name")
    if payload.last_name is not None:
        user.last_name = payload.last_name.strip()
        updates.append("last_name")

    if updates:
        user.save(update_fields=updates)

    return 200, user
