from typing import List
from ninja import Router
from ninja.errors import HttpError

from apps.accounts.security import JWTAuth
from apps.tours.models import Feedback
from apps.tours.schemas import FeedbackIn, FeedbackOut, ErrorOut

router = Router(tags=["Feedback & Suggestions"], auth=JWTAuth())


@router.post(
    "/",
    response={201: FeedbackOut, 400: ErrorOut, 403: ErrorOut},
    summary="Submit user suggestion or complaint",
)
def submit_feedback(request, payload: FeedbackIn):
    """
    Submits a user suggestion or complaint with the authenticated user's name and email.
    Locked for demo accounts.
    """
    user = request.auth
    if getattr(user, "email", None) == "alex@tourmate.test":
        raise HttpError(403, "ডেমো অ্যাকাউন্টে মতামত বা অভিযোগ পাঠানো বন্ধ রাখা হয়েছে (Demo account feedback is locked).")

    if not payload.message.strip():
        return 400, {"detail": "Message cannot be empty."}

    user_name = user.get_full_name().strip() if user.get_full_name() else user.email.split("@")[0]

    feedback = Feedback.objects.create(
        user=user,
        user_name=user_name,
        user_email=user.email,
        feedback_type=payload.feedback_type,
        message=payload.message.strip(),
    )

    return 201, feedback


@router.get(
    "/",
    response={200: List[FeedbackOut]},
    summary="Get recent suggestions and complaints",
)
def list_feedbacks(request):
    """
    Returns recent community suggestions and complaints feed.
    """
    feedbacks = Feedback.objects.all().order_by("-created_at")[:25]
    return 200, list(feedbacks)
