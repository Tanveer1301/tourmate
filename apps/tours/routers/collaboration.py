from typing import List
from uuid import UUID

from django.shortcuts import get_object_or_404
from ninja import Router

from apps.tours.models import ActivityLog, Expense, ExpenseComment, TourMember
from apps.tours.permissions import require_tour_access
from apps.tours.schemas import (
    ActivityLogOut,
    ErrorOut,
    ExpenseCommentIn,
    ExpenseCommentOut,
)
from apps.tours.services.settlement import SettlementService

router = Router(tags=["Collaboration"])


@router.post(
    "/{tour_id}/expenses/{expense_id}/comments",
    response={201: ExpenseCommentOut, 403: ErrorOut, 404: ErrorOut},
    summary="Add a comment to an expense",
)
def add_expense_comment(
    request,
    tour_id: UUID,
    expense_id: int,
    payload: ExpenseCommentIn,
):
    """
    Adds a collaborative comment or discussion note to a specific expense.
    Requires at least COMMENTER privileges.
    """
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.COMMENTER)
    expense = get_object_or_404(Expense, id=expense_id, tour=tour)

    comment = ExpenseComment.objects.create(
        expense=expense,
        author=request.auth,
        comment=payload.comment.strip(),
    )

    SettlementService.record_activity(
        tour_id=tour.id,
        actor=request.auth,
        action="COMMENT_ADDED",
        details={
            "expense_id": expense.id,
            "expense_purpose": expense.purpose,
            "comment_preview": comment.comment[:50],
        },
    )

    return 201, comment


@router.get(
    "/{tour_id}/activity",
    response={200: List[ActivityLogOut], 403: ErrorOut, 404: ErrorOut},
    summary="Get recent activity feed for the tour",
)
def get_tour_activity(request, tour_id: UUID):
    """
    Returns the real-time activity log for mobile trip feeds.
    Optimized with select_related('actor') to eliminate N+1 queries.
    """
    require_tour_access(request.auth, tour_id, min_role=TourMember.Role.VIEWER)

    activities = (
        ActivityLog.objects.filter(tour_id=tour_id)
        .select_related("actor")
        .order_by("-timestamp")[:50]
    )

    return 200, activities
