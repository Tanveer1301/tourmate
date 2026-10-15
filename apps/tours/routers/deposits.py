from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from apps.tours.models import Deposit, TourMember
from apps.tours.permissions import require_tour_access
from apps.tours.schemas import (
    DepositCreateIn,
    DepositOut,
    DepositUpdateIn,
    ErrorOut,
    SuccessOut,
)
from apps.tours.services.settlement import SettlementService, round_currency

router = Router(tags=["Deposits"])


@router.post(
    "/{tour_id}/deposits",
    response={201: DepositOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Add a deposit entry for a member into the Common Fund",
)
def create_deposit(request, tour_id: UUID, payload: DepositCreateIn):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)
    if tour.is_archived:
        raise HttpError(400, "এই ট্যুরটি আর্কাইভ করা হয়েছে। হিসাব লক করা। (Tour is archived and locked).")
    member = get_object_or_404(TourMember, id=payload.member_id, tour=tour)

    amount = round_currency(payload.amount)
    if amount <= 0:
        raise HttpError(400, "Deposit amount must be greater than zero.")

    with transaction.atomic():
        deposit = Deposit.objects.create(
            tour=tour,
            member=member,
            amount=amount,
            note=payload.note or "",
        )

        SettlementService.record_activity(
            tour_id=tour.id,
            actor=request.auth,
            action="DEPOSIT_ADDED",
            details={
                "member_name": member.name,
                "amount": str(deposit.amount),
                "note": deposit.note,
            },
        )

    deposit = (
        Deposit.objects.select_related("member", "member__user")
        .get(id=deposit.id)
    )

    return 201, deposit


@router.put(
    "/{tour_id}/deposits/{deposit_id}",
    response={200: DepositOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Update an existing deposit (Editor or Owner)",
)
def update_deposit(request, tour_id: UUID, deposit_id: int, payload: DepositUpdateIn):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)
    if tour.is_archived:
        raise HttpError(400, "এই ট্যুরটি আর্কাইভ করা হয়েছে। হিসাব লক করা। (Tour is archived and locked).")
    deposit = get_object_or_404(Deposit, id=deposit_id, tour=tour)

    updates = []
    old_amount = deposit.amount
    old_note = deposit.note or ""

    if payload.amount is not None:
        amt = round_currency(payload.amount)
        if amt <= 0:
            raise HttpError(400, "Deposit amount must be greater than zero.")
        deposit.amount = amt
        updates.append("amount")

    if payload.note is not None:
        deposit.note = payload.note.strip()
        updates.append("note")

    if updates:
        deposit.save(update_fields=updates)
        changes = []
        if str(old_amount) != str(deposit.amount):
            changes.append({"field": "amount", "old": str(old_amount), "new": str(deposit.amount)})
        if old_note != (deposit.note or ""):
            changes.append({"field": "note", "old": old_note or "-", "new": deposit.note or "-"})

        SettlementService.record_activity(
            tour_id=tour.id,
            actor=request.auth,
            action="DEPOSIT_UPDATED",
            details={
                "member_name": deposit.member.name,
                "old_amount": str(old_amount),
                "new_amount": str(deposit.amount),
                "note": deposit.note,
                "changes": changes,
            },
        )

    return 200, deposit


@router.delete(
    "/{tour_id}/deposits/{deposit_id}",
    response={200: SuccessOut, 403: ErrorOut, 404: ErrorOut},
    summary="Delete a deposit entry (Editor or Owner)",
)
def delete_deposit(request, tour_id: UUID, deposit_id: int):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)
    if tour.is_archived:
        raise HttpError(400, "এই ট্যুরটি আর্কাইভ করা হয়েছে। হিসাব লক করা। (Tour is archived and locked).")
    deposit = get_object_or_404(Deposit, id=deposit_id, tour=tour)

    member_name = deposit.member.name
    amt = str(deposit.amount)
    deposit.delete()

    SettlementService.record_activity(
        tour_id=tour.id,
        actor=request.auth,
        action="DEPOSIT_DELETED",
        details={
            "member_name": member_name,
            "amount": amt,
        },
    )

    return 200, {"success": True, "message": f"Deposit of ৳ {amt} for {member_name} has been removed."}
