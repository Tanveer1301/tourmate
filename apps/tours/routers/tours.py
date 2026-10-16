from decimal import Decimal
from typing import List
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from apps.tours.models import Deposit, Expense, Tour, TourMember
from apps.tours.permissions import require_tour_access
from apps.tours.schemas import (
    DepositItemOut,
    ErrorOut,
    SuccessOut,
    TourCreateIn,
    TourDashboardOut,
    TourDetailOut,
    TourListOut,
    TourMemberDepositOut,
    TourMemberOut,
    TourMemberUpdateIn,
    TourShareIn,
    TourSummaryOut,
    TourUpdateIn,
)
from apps.tours.services.invitation import send_tour_invitation_email
from apps.tours.services.settlement import SettlementService, round_currency

User = get_user_model()
router = Router(tags=["Tours"])


@router.get(
    "/",
    response=List[TourListOut],
    summary="List all tours for the authenticated user",
)
def list_tours(request):
    user = request.auth
    if user.email:
        TourMember.objects.filter(email__iexact=user.email, user__isnull=True).update(user=user)

    # Demo user (Alex) must ONLY ever see the demo showcase tour
    if user.email == "alex@tourmate.test":
        tours = list(
            Tour.objects.filter(id="6c718b10-c0e7-4ca7-9c71-66b320f94a8d")
            .annotate(members_count_annotated=Count("members", distinct=True))
            .order_by("-created_at")
        )
    else:
        # Real users only see tours they created or are an explicit member of
        tours = list(
            Tour.objects.filter(
                Q(members__user=user) | Q(members__email__iexact=user.email) | Q(created_by=user)
            )
            .exclude(id="6c718b10-c0e7-4ca7-9c71-66b320f94a8d")
            .distinct()
            .annotate(members_count_annotated=Count("members", distinct=True))
            .order_by("-created_at")
        )

    if not tours:
        return []

    tour_ids = [t.id for t in tours]

    deposit_totals = {
        row["tour_id"]: round_currency(row["total"])
        for row in Deposit.objects.filter(tour_id__in=tour_ids)
        .values("tour_id")
        .annotate(total=Sum("amount"))
    }

    expense_totals = {
        row["tour_id"]: round_currency(row["total"])
        for row in Expense.objects.filter(tour_id__in=tour_ids)
        .values("tour_id")
        .annotate(total=Sum("amount"))
    }

    results = []
    for t in tours:
        credit = deposit_totals.get(t.id, Decimal("0.00"))
        debit = expense_totals.get(t.id, Decimal("0.00"))
        remaining = round_currency(credit - debit)
        count = getattr(t, "members_count_annotated", 0)

        results.append({
            "id": t.id,
            "title": t.title,
            "description": t.description or "",
            "color_theme": t.color_theme,
            "budget_limit": t.budget_limit,
            "is_archived": t.is_archived,
            "total_credit": credit,
            "total_debit": debit,
            "remaining_balance": remaining,
            "members_count": count,
            "created_at": t.created_at,
        })

    return results


@router.post(
    "/",
    response={201: TourDetailOut},
    summary="Create a new tour",
)
def create_tour(request, payload: TourCreateIn):
    user = request.auth

    with transaction.atomic():
        tour = Tour.objects.create(
            title=payload.title,
            description=payload.description or "",
            color_theme=payload.color_theme or "#3B82F6",
            budget_limit=payload.budget_limit,
            created_by=user,
        )

        TourMember.objects.create(
            tour=tour,
            user=user,
            name=user.full_name or user.email,
            email=user.email,
            role=TourMember.Role.OWNER,
        )

        SettlementService.record_activity(
            tour_id=tour.id,
            actor=user,
            action="TOUR_CREATED",
            details={"title": tour.title, "budget_limit": str(tour.budget_limit or "")},
        )

    return 201, tour


@router.put(
    "/{tour_id}",
    response={200: TourDetailOut, 403: ErrorOut, 404: ErrorOut},
    summary="Update tour details (Editor or Owner)",
)
def update_tour(request, tour_id: UUID, payload: TourUpdateIn):
    tour, member = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)

    old_title = tour.title
    old_desc = tour.description
    old_budget = str(tour.budget_limit) if tour.budget_limit else ""

    updates = []
    if payload.title is not None and payload.title.strip():
        tour.title = payload.title.strip()
        updates.append("title")
    if payload.description is not None:
        tour.description = payload.description.strip()
        updates.append("description")
    if payload.color_theme is not None:
        tour.color_theme = payload.color_theme
        updates.append("color_theme")
    if payload.clear_budget:
        tour.budget_limit = None
        updates.append("budget_limit")
    elif payload.budget_limit is not None:
        tour.budget_limit = payload.budget_limit
        updates.append("budget_limit")
    if payload.is_archived is not None:
        tour.is_archived = payload.is_archived
        updates.append("is_archived")

    if updates:
        tour.save(update_fields=updates)
        changes = []
        if old_title != tour.title:
            changes.append({"field": "title", "old": old_title, "new": tour.title})
        new_budget = str(tour.budget_limit) if tour.budget_limit else ""
        if old_budget != new_budget:
            changes.append({"field": "budget", "old": old_budget or "নেই", "new": new_budget or "নেই"})
        if old_desc != tour.description:
            changes.append({"field": "description", "old": old_desc or "-", "new": tour.description or "-"})

        SettlementService.record_activity(
            tour_id=tour.id,
            actor=request.auth,
            action="TOUR_UPDATED",
            details={"fields": updates, "title": tour.title, "changes": changes},
        )

    return 200, tour


@router.post(
    "/{tour_id}/toggle-archive",
    response={200: TourDetailOut, 403: ErrorOut, 404: ErrorOut},
    summary="Toggle archive/lock status of the tour (Owner only)",
)
def toggle_archive_tour(request, tour_id: UUID):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.OWNER)
    tour.is_archived = not tour.is_archived
    tour.save(update_fields=["is_archived"])

    SettlementService.record_activity(
        tour_id=tour.id,
        actor=request.auth,
        action="TOUR_ARCHIVED" if tour.is_archived else "TOUR_UNARCHIVED",
        details={"is_archived": tour.is_archived, "title": tour.title},
    )
    return 200, tour


@router.delete(
    "/{tour_id}",
    response={200: SuccessOut, 403: ErrorOut, 404: ErrorOut},
    summary="Delete tour (Owner only)",
)
def delete_tour(request, tour_id: UUID):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.OWNER)

    title = tour.title
    tour.delete()

    return 200, {"success": True, "message": f"Tour '{title}' has been deleted."}


@router.get(
    "/{tour_id}/dashboard",
    response={200: TourDashboardOut, 403: ErrorOut, 404: ErrorOut},
    summary="Get optimized mobile dashboard payload",
)
def get_tour_dashboard(request, tour_id: UUID):
    # 1. Fetch members with tour, tour creator, and users in ONE single round-trip
    members_qs = list(
        TourMember.objects.select_related("tour__created_by", "user")
        .filter(tour_id=tour_id)
        .order_by("joined_at")
    )
    user = request.auth
    tour = None
    membership = None

    if members_qs:
        tour = members_qs[0].tour
        membership = next(
            (m for m in members_qs if m.user_id == user.id or (user.email and m.email and m.email.lower() == user.email.lower())),
            None,
        )

    if not tour or not membership:
        tour, membership = require_tour_access(user, tour_id, min_role=TourMember.Role.VIEWER)
        if getattr(membership, "id", None) and not any(m.id == membership.id for m in members_qs):
            members_qs.append(membership)

    # 2. Fetch all deposits in a single query
    all_deposits = list(Deposit.objects.filter(tour_id=tour_id).order_by("created_at"))

    # 3. Fetch recent expenses in a single query (+ prefetch)
    recent_expenses = list(
        Expense.objects.filter(tour_id=tour_id)
        .select_related("paid_by", "created_by")
        .prefetch_related("tagged_members")
        .annotate(comments_count=Count("comments"))
        .order_by("-created_at")[:50]
    )

    # In-memory calculations (0ms latency, zero database round-trips)
    deposits_by_member = {}
    member_deposit_totals = {}
    total_credit = Decimal("0.00")

    for dep in all_deposits:
        dep_amt = round_currency(dep.amount)
        total_credit += dep_amt
        deposits_by_member.setdefault(dep.member_id, []).append(
            DepositItemOut(
                id=dep.id,
                amount=dep_amt,
                note=dep.note or "",
                created_at=dep.created_at,
            )
        )
        member_deposit_totals[dep.member_id] = member_deposit_totals.get(dep.member_id, Decimal("0.00")) + dep_amt

    if len(recent_expenses) < 50:
        total_debit = round_currency(sum((e.amount for e in recent_expenses), Decimal("0.00")))
    else:
        debit_agg = Expense.objects.filter(tour_id=tour_id).aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))
        total_debit = round_currency(debit_agg["total"])

    total_credit = round_currency(total_credit)
    remaining_balance = round_currency(total_credit - total_debit)

    budget_progress = None
    if tour.budget_limit and tour.budget_limit > Decimal("0.00"):
        raw_progress = (total_debit / tour.budget_limit) * Decimal("100.00")
        budget_progress = round_currency(raw_progress)

    summary = TourSummaryOut(
        total_credit=total_credit,
        total_debit=total_debit,
        remaining_balance=remaining_balance,
        budget_limit=tour.budget_limit,
        budget_progress=budget_progress,
    )

    member_items = []
    for m in members_qs:
        total_dep = round_currency(member_deposit_totals.get(m.id, Decimal("0.00")))
        m_deps = deposits_by_member.get(m.id, [])
        if m_deps:
            parts = [
                f"{int(d.amount)}" if d.amount % Decimal("1") == Decimal("0") else f"{d.amount}"
                for d in m_deps
            ]
            if len(parts) > 1:
                breakdown_str = f"{' + '.join(parts)} = ৳ {total_dep}"
            else:
                breakdown_str = f"৳ {total_dep}"
        else:
            breakdown_str = "৳ 0.00"

        member_items.append(
            TourMemberDepositOut(
                member=TourMemberOut(
                    id=m.id,
                    name=m.name,
                    email=m.email,
                    role=m.role,
                    designation=getattr(m, "designation", "") or "",
                    joined_at=m.joined_at,
                    user_id=m.user_id,
                ),
                total_deposited=total_dep,
                deposits=m_deps,
                breakdown_str=breakdown_str,
            )
        )

    return 200, {
        "tour": tour,
        "summary": summary,
        "members": member_items,
        "recent_expenses": recent_expenses,
    }


@router.post(
    "/{tour_id}/share",
    response={200: TourMemberOut, 201: TourMemberOut, 403: ErrorOut, 404: ErrorOut},
    summary="Invite or share tour access with an email",
)
def share_tour(request, tour_id: UUID, payload: TourShareIn):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)

    normalized_email = payload.email.strip().lower() if payload.email and payload.email.strip() else None
    member_name = payload.name.strip() if payload.name and payload.name.strip() else None

    if not normalized_email and not member_name:
        return 400, {"detail": "সদস্যের নাম বা ইমেইল ঠিকানা দিন (Member name or email is required)."}

    linked_user = None
    if normalized_email:
        linked_user = User.objects.filter(email__iexact=normalized_email).first()
        if not member_name and linked_user:
            member_name = linked_user.full_name or linked_user.email
        if not member_name:
            member_name = normalized_email.split("@")[0]

    designation_val = payload.designation.strip() if payload.designation else ""
    with transaction.atomic():
        if normalized_email:
            member, created = TourMember.objects.get_or_create(
                tour=tour,
                email=normalized_email,
                defaults={
                    "name": member_name,
                    "role": payload.role,
                    "designation": designation_val,
                    "user": linked_user,
                },
            )
            if not created:
                member.role = payload.role
                if payload.designation is not None:
                    member.designation = designation_val
                if payload.name:
                    member.name = payload.name.strip()
                if linked_user and not member.user:
                    member.user = linked_user
                member.save()
        else:
            member = TourMember.objects.create(
                tour=tour,
                name=member_name,
                email=None,
                role=payload.role,
                designation=designation_val,
                user=None,
            )
            created = True

        SettlementService.record_activity(
            tour_id=tour.id,
            actor=request.auth,
            action="MEMBER_INVITED" if created else "MEMBER_UPDATED",
            details={
                "email": normalized_email or "No Email",
                "role": payload.role,
                "designation": member.designation,
                "name": member.name,
                "created": created,
            },
        )

        if normalized_email:
            send_tour_invitation_email(tour, member, inviter=request.auth, request=request)

    return 201 if created else 200, member


@router.put(
    "/{tour_id}/members/{member_id}",
    response={200: TourMemberOut, 403: ErrorOut, 404: ErrorOut},
    summary="Update tour member name/nickname or role or designation",
)
def update_member(request, tour_id: UUID, member_id: int, payload: TourMemberUpdateIn):
    tour, current_member = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.EDITOR)
    target_member = get_object_or_404(TourMember, id=member_id, tour=tour)

    old_name = target_member.name
    old_role = target_member.role
    old_email = target_member.email
    old_designation = target_member.designation
    updates = []
    if payload.name is not None and payload.name.strip():
        target_member.name = payload.name.strip()
        updates.append("name")

    if payload.email is not None:
        normalized_email = payload.email.strip().lower() if payload.email.strip() else None
        target_member.email = normalized_email
        if normalized_email:
            linked_user = User.objects.filter(email__iexact=normalized_email).first()
            target_member.user = linked_user
        else:
            target_member.user = None
        updates.extend(["email", "user"])

    if payload.role is not None:
        # Changing role requires OWNER privileges
        if current_member.role != TourMember.Role.OWNER and tour.created_by_id != request.auth.id:
            raise HttpError(403, "Only the tour Owner can modify member roles.")
        target_member.role = payload.role
        updates.append("role")

    if payload.designation is not None:
        target_member.designation = payload.designation.strip()
        updates.append("designation")

    if updates:
        target_member.save(update_fields=updates)
        changes = []
        if old_name != target_member.name:
            changes.append({"field": "name", "old": old_name, "new": target_member.name})
        if old_email != target_member.email:
            changes.append({"field": "email", "old": old_email or "None", "new": target_member.email or "None"})
        if old_role != target_member.role:
            changes.append({"field": "role", "old": old_role, "new": target_member.role})
        if old_designation != target_member.designation:
            changes.append({"field": "designation", "old": old_designation, "new": target_member.designation})

        SettlementService.record_activity(
            tour_id=tour.id,
            actor=request.auth,
            action="MEMBER_UPDATED",
            details={
                "member_id": target_member.id,
                "name": target_member.name,
                "role": target_member.role,
                "changes": changes,
            },
        )

        if "email" in updates and target_member.email and old_email != target_member.email:
            send_tour_invitation_email(tour, target_member, inviter=request.auth, request=request)

    return 200, target_member


@router.delete(
    "/{tour_id}/members/{member_id}",
    response={200: SuccessOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Remove a member from tour (Owner only)",
)
def delete_member(request, tour_id: UUID, member_id: int):
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.OWNER)
    target_member = get_object_or_404(TourMember, id=member_id, tour=tour)

    # Owner cannot delete themselves
    if target_member.role == TourMember.Role.OWNER or target_member.user_id == tour.created_by_id or (target_member.user and target_member.user_id == request.auth.id):
        raise HttpError(400, "ট্যুর ওনারকে ডিলিট করা সম্ভব নয়। (The Tour Owner cannot be deleted from the tour).")

    name = target_member.name
    target_member.delete()

    SettlementService.record_activity(
        tour_id=tour.id,
        actor=request.auth,
        action="MEMBER_REMOVED",
        details={"name": name},
    )

    return 200, {"success": True, "message": f"Member '{name}' has been removed."}
