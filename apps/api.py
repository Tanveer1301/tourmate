from ninja import NinjaAPI
from ninja.errors import ValidationError

from apps.accounts.security import JWTAuth
from apps.tours.routers import (
    auth_router,
    collaboration_router,
    deposits_router,
    expenses_router,
    feedback_router,
    settlement_router,
    tours_router,
)

# Initialize primary API instance with global JWT bearer authentication
api = NinjaAPI(
    title="TourMate Backend API",
    version="1.0.0",
    description=(
        "Production-ready mobile-first trip expense tracker backend operating on a "
        "Tour Manager / Common Fund (Deposit) architecture with automated settlement balancing."
    ),
    auth=JWTAuth(),
    docs_url="/docs",
)


@api.exception_handler(ValidationError)
def validation_error_handler(request, exc):
    """Formats validation errors into standard clean JSON response."""
    return api.create_response(
        request,
        {"detail": "Validation error", "errors": exc.errors},
        status=422,
    )


# 1. Mount Auth router without requiring an existing JWT
api.add_router("/auth", auth_router, auth=None)

# 2. Mount Tour-scoped domain routers (protected by JWTAuth)
api.add_router("/tours", tours_router)
api.add_router("/tours", deposits_router)
api.add_router("/tours", expenses_router)
api.add_router("/tours", settlement_router)
api.add_router("/tours", collaboration_router)

# 3. Mount User Feedback & Suggestions router
api.add_router("/feedback", feedback_router)

