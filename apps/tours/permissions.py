from typing import Optional, Tuple
from uuid import UUID

from django.shortcuts import get_object_or_404
from ninja.errors import HttpError

from apps.tours.models import Tour, TourMember

ROLE_LEVELS = {
    TourMember.Role.VIEWER: 1,
    TourMember.Role.COMMENTER: 2,
    TourMember.Role.EDITOR: 3,
    TourMember.Role.OWNER: 4,
}


def require_tour_access(
    user,
    tour_id: UUID,
    min_role: str = TourMember.Role.VIEWER,
) -> Tuple[Tour, TourMember]:
    """
    Verifies that the authenticated user has at least the required role in the tour.
    Returns a tuple of (Tour, TourMember).
    Raises HttpError(404) if tour not found, or HttpError(403) if access denied.
    """
    # Fast path: query membership with joined tour in a single SQL round-trip
    membership = (
        TourMember.objects.select_related("tour")
        .filter(tour_id=tour_id, user=user)
        .first()
    )

    if membership:
        tour = membership.tour
    else:
        # Fallback path: verify tour exists, then check matching by email or creator
        tour = get_object_or_404(Tour, id=tour_id)
        if user.email:
            membership = TourMember.objects.filter(tour=tour, email__iexact=user.email).first()
            if membership and not membership.user:
                membership.user = user
                membership.save(update_fields=["user"])

        if not membership:
            if tour.created_by_id == user.id:
                membership, _ = TourMember.objects.get_or_create(
                    tour=tour,
                    user=user,
                    defaults={
                        "name": user.full_name or user.email,
                        "email": user.email,
                        "role": TourMember.Role.OWNER,
                    },
                )
            elif (tour.created_by and tour.created_by.email == "alex@tourmate.test") or str(tour.id) == "6c718b10-c0e7-4ca7-9c71-66b320f94a8d":
                # Demo Showcase Tour ONLY: In-memory read-only viewer without database persistence
                membership = TourMember(
                    tour=tour,
                    user=user,
                    name=getattr(user, "full_name", "") or "Guest",
                    email=getattr(user, "email", ""),
                    role=TourMember.Role.VIEWER,
                )
            elif getattr(user, "is_super_admin", False) or getattr(user, "is_superuser", False):
                # Super Admin God-Mode: In-memory OWNER access across all tours
                membership = TourMember(
                    id=0,
                    tour=tour,
                    user=user,
                    name=getattr(user, "full_name", "") or "Super Admin",
                    email=getattr(user, "email", "") or "",
                    role=TourMember.Role.OWNER,
                )
            else:
                raise HttpError(403, "You do not have access to this tour.")

    # Super Admin always possesses OWNER privileges across any tour
    if getattr(user, "is_super_admin", False) or getattr(user, "is_superuser", False):
        membership.role = TourMember.Role.OWNER

    user_level = ROLE_LEVELS.get(membership.role, 0)
    required_level = ROLE_LEVELS.get(min_role, 1)

    if user_level < required_level:
        raise HttpError(
            403,
            f"Action requires '{min_role}' privileges. Current role: '{membership.role}'.",
        )

    return tour, membership
