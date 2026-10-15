from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from apps.tours.models import Expense, TourMember
from apps.tours.permissions import require_tour_access
from apps.tours.schemas import (
    ErrorOut,
    ExpenseCreateIn,
    ExpenseOut,
    ExpenseSuggestionsOut,
    ExpenseUpdateIn,
    SuccessOut,
)
from apps.tours.services.settlement import SettlementService, round_currency

router = Router(tags=["Expenses"])


@router.get(
    "/{tour_id}/expenses/suggestions",
    response=ExpenseSuggestionsOut,
    summary="Get autocomplete purpose suggestions (user recent + global popular)",
)
def expense_suggestions(request, tour_id: UUID):
    user = request.auth

    my_recent_qs = (
        Expense.objects.filter(created_by=user)
        .values("purpose")
        .annotate(usage_count=Count("id"))
        .order_by("-usage_count", "purpose")[:8]
    )
    my_recent = [item["purpose"] for item in my_recent_qs]

    global_qs = (
        Expense.objects.values("purpose")
        .annotate(usage_count=Count("id"))
        .order_by("-usage_count", "purpose")[:8]
    )
    global_popular = [item["purpose"] for item in global_qs]

    return {
        "my_recent": my_recent,
        "global_popular": global_popular,
    }


@router.post(
    "/{tour_id}/expenses",
    response={201: ExpenseOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Log a new expense with selective member splitting",
)
def create_expense(request, tour_id: UUID, payload: ExpenseCreateIn):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)

    if tour.is_archived:
        raise HttpError(400, "এই ট্যুরটি আর্কাইভ করা হয়েছে। হিসাব লক করা। (Tour is archived and locked).")

    amount = round_currency(payload.amount)
    if amount <= Decimal("0.00"):
        raise HttpError(400, "Expense amount must be greater than zero.")

    paid_by_member: Optional[TourMember] = None
    if payload.paid_by_id is not None:
        paid_by_member = get_object_or_404(TourMember, id=payload.paid_by_id, tour=tour)

    all_tour_members = list(TourMember.objects.filter(tour=tour))
    if not all_tour_members:
        raise HttpError(400, "Tour must have at least one member to record an expense.")

    if payload.tagged_member_ids:
        valid_member_map = {m.id: m for m in all_tour_members}
        invalid_ids = [mid for mid in payload.tagged_member_ids if mid not in valid_member_map]
        if invalid_ids:
            raise HttpError(400, f"Member IDs {invalid_ids} do not belong to this tour.")
        if len(payload.tagged_member_ids) >= len(all_tour_members):
            selected_members = []
        else:
            selected_members = [valid_member_map[mid] for mid in payload.tagged_member_ids]
    else:
        selected_members = []

    with transaction.atomic():
        expense = Expense.objects.create(
            tour=tour,
            purpose=payload.purpose.strip(),
            amount=amount,
            paid_by=paid_by_member,
            note=payload.note.strip() if payload.note else "",
            receipt_image=payload.receipt_image or "",
            created_by=request.auth,
        )
        if selected_members:
            expense.tagged_members.set(selected_members)
        else:
            expense.tagged_members.clear()

        payer_desc = paid_by_member.name if paid_by_member else "Common Tour Fund"
        tagged_names = [m.name for m in selected_members] if selected_members else ["All Members"]
        SettlementService.record_activity(
            tour_id=tour.id,
            actor=request.auth,
            action="EXPENSE_CREATED",
            details={
                "purpose": expense.purpose,
                "amount": str(expense.amount),
                "paid_by": payer_desc,
                "tagged": ", ".join(tagged_names),
                "note": expense.note,
            },
        )

    expense = (
        Expense.objects.select_related("paid_by", "created_by")
        .prefetch_related("tagged_members")
        .annotate(comments_count=Count("comments"))
        .get(id=expense.id)
    )

    return 201, expense


@router.put(
    "/{tour_id}/expenses/{expense_id}",
    response={200: ExpenseOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Update an existing expense (Editor or Owner)",
)
def update_expense(request, tour_id: UUID, expense_id: int, payload: ExpenseUpdateIn):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)
    if tour.is_archived:
        raise HttpError(400, "এই ট্যুরটি আর্কাইভ করা হয়েছে। হিসাব লক করা। (Tour is archived and locked).")
    expense = get_object_or_404(Expense, id=expense_id, tour=tour)

    all_tour_members = list(TourMember.objects.filter(tour=tour))
    valid_member_map = {m.id: m for m in all_tour_members}

    # Capture old values for audit diff
    old_purpose = expense.purpose
    old_amount = str(expense.amount)
    old_payer = expense.paid_by.name if expense.paid_by else "Common Tour Fund"
    old_note = expense.note or ""
    old_tagged = ", ".join([m.name for m in expense.tagged_members.all()])

    with transaction.atomic():
        updates = []
        if payload.purpose is not None and payload.purpose.strip():
            expense.purpose = payload.purpose.strip()
            updates.append("purpose")

        if payload.amount is not None:
            amt = round_currency(payload.amount)
            if amt <= Decimal("0.00"):
                raise HttpError(400, "Expense amount must be greater than zero.")
            expense.amount = amt
            updates.append("amount")

        if payload.paid_by_id is not None:
            if payload.paid_by_id == 0 or payload.paid_by_id is None:
                expense.paid_by = None
            else:
                expense.paid_by = get_object_or_404(TourMember, id=payload.paid_by_id, tour=tour)
            updates.append("paid_by")

        if payload.note is not None:
            expense.note = payload.note.strip()
            updates.append("note")

        if payload.receipt_image is not None:
            expense.receipt_image = payload.receipt_image
            updates.append("receipt_image")

        if updates:
            expense.save(update_fields=updates)

        if payload.tagged_member_ids is not None:
            if payload.tagged_member_ids and len(payload.tagged_member_ids) < len(all_tour_members):
                selected_members = [valid_member_map[mid] for mid in payload.tagged_member_ids if mid in valid_member_map]
                expense.tagged_members.set(selected_members)
            else:
                expense.tagged_members.clear()

        tagged_names = [m.name for m in expense.tagged_members.all()]
        payer_desc = expense.paid_by.name if expense.paid_by else "Common Tour Fund"
        new_tagged = ", ".join(tagged_names) if tagged_names else "All Members"

        # Build exact change diffs
        changes = []
        if old_purpose != expense.purpose:
            changes.append({"field": "purpose", "old": old_purpose, "new": expense.purpose})
        if old_amount != str(expense.amount):
            changes.append({"field": "amount", "old": old_amount, "new": str(expense.amount)})
        if old_payer != payer_desc:
            changes.append({"field": "paid_by", "old": old_payer, "new": payer_desc})
        if old_note != expense.note:
            changes.append({"field": "note", "old": old_note or "-", "new": expense.note or "-"})
        if old_tagged != new_tagged:
            changes.append({"field": "tagged", "old": old_tagged, "new": new_tagged})

        SettlementService.record_activity(
            tour_id=tour.id,
            actor=request.auth,
            action="EXPENSE_UPDATED",
            details={
                "purpose": expense.purpose,
                "amount": str(expense.amount),
                "paid_by": payer_desc,
                "tagged": new_tagged,
                "note": expense.note,
                "changes": changes,
            },
        )

    expense = (
        Expense.objects.select_related("paid_by", "created_by")
        .prefetch_related("tagged_members")
        .annotate(comments_count=Count("comments"))
        .get(id=expense.id)
    )

    return 200, expense


@router.delete(
    "/{tour_id}/expenses/{expense_id}",
    response={200: SuccessOut, 403: ErrorOut, 404: ErrorOut},
    summary="Delete an expense (Editor or Owner)",
)
def delete_expense(request, tour_id: UUID, expense_id: int):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)
    if tour.is_archived:
        raise HttpError(400, "এই ট্যুরটি আর্কাইভ করা হয়েছে। হিসাব লক করা। (Tour is archived and locked).")
    expense = get_object_or_404(Expense, id=expense_id, tour=tour)

    purpose = expense.purpose
    amt = str(expense.amount)
    expense.delete()

    SettlementService.record_activity(
        tour_id=tour.id,
        actor=request.auth,
        action="EXPENSE_DELETED",
        details={
            "purpose": purpose,
            "amount": amt,
        },
    )

    return 200, {"success": True, "message": f"Expense '{purpose}' (৳ {amt}) has been deleted."}
