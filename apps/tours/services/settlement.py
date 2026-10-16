from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from uuid import UUID

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from apps.tours.models import ActivityLog, Deposit, Expense, Tour, TourMember

TWOPLACES = Decimal("0.01")
ZERO_CURRENCY = Decimal("0.00")


def round_currency(val: Decimal) -> Decimal:
    """Helper to round any Decimal to 2 decimal places using standard ROUND_HALF_UP."""
    return val.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class SettlementService:
    """
    Production-grade financial calculation engine for TourMate.
    Guarantees strict financial precision, prevents N+1 queries,
    and calculates accurate member balance sheets and settlements.
    """

    @staticmethod
    def get_tour_summary(tour_id: UUID, tour: Optional[Tour] = None) -> Dict[str, Any]:
        if tour is None:
            tour = get_object_or_404(Tour, id=tour_id)

        total_credit_data = Deposit.objects.filter(tour_id=tour_id).aggregate(
            total=Coalesce(Sum("amount"), ZERO_CURRENCY)
        )
        total_debit_data = Expense.objects.filter(tour_id=tour_id).aggregate(
            total=Coalesce(Sum("amount"), ZERO_CURRENCY)
        )

        total_credit: Decimal = round_currency(total_credit_data["total"])
        total_debit: Decimal = round_currency(total_debit_data["total"])
        remaining_balance: Decimal = round_currency(total_credit - total_debit)

        budget_progress: Optional[Decimal] = None
        if tour.budget_limit and tour.budget_limit > ZERO_CURRENCY:
            raw_progress = (total_debit / tour.budget_limit) * Decimal("100.00")
            budget_progress = round_currency(raw_progress)

        return {
            "tour": tour,
            "total_credit": total_credit,
            "total_debit": total_debit,
            "remaining_balance": remaining_balance,
            "budget_limit": tour.budget_limit,
            "budget_progress": budget_progress,
        }

    @staticmethod
    def get_member_settlements(tour_id: UUID, tour: Optional[Tour] = None) -> Dict[str, Any]:
        """
        Calculates the complete balance sheet for every member in the tour:
        - total_deposited: Total funds contributed to the common fund.
        - out_of_pocket_paid: Total expenses paid directly by this member.
        - allocated_expense: Fair share of all tagged/split expenses assigned to this member.
        - net_balance: (total_deposited + out_of_pocket_paid) - allocated_expense.
        - status: 'REFUNDABLE' (if > 0), 'PAYABLE' (if < 0), or 'SETTLED' (if == 0).
        - deposits_list: List of deposits made by this member.
        - paid_expenses_list: List of expenses paid directly by this member.
        - consumed_expenses_list: List of all expenses shared by this member with per-head share.
        """
        if tour is None:
            tour = get_object_or_404(Tour, id=tour_id)

        # 1. Fetch all tour members
        members: List[TourMember] = list(
            TourMember.objects.filter(tour_id=tour_id).select_related("user")
        )
        all_member_ids = [m.id for m in members]
        member_lookup = {m.id: m for m in members}

        deposited_map: Dict[int, Decimal] = {m_id: ZERO_CURRENCY for m_id in all_member_ids}
        out_of_pocket_map: Dict[int, Decimal] = {m_id: ZERO_CURRENCY for m_id in all_member_ids}
        allocated_expense_map: Dict[int, Decimal] = {m_id: ZERO_CURRENCY for m_id in all_member_ids}

        # Itemized lists for detailed member ledger view
        deposits_list_map: Dict[int, List[Dict[str, Any]]] = {m_id: [] for m_id in all_member_ids}
        paid_expenses_map: Dict[int, List[Dict[str, Any]]] = {m_id: [] for m_id in all_member_ids}
        consumed_expenses_map: Dict[int, List[Dict[str, Any]]] = {m_id: [] for m_id in all_member_ids}

        # 2. Fetch all deposits
        all_deposits = list(Deposit.objects.filter(tour_id=tour_id).order_by("created_at"))
        for dep in all_deposits:
            m_id = dep.member_id
            if m_id in deposited_map:
                dep_amt = round_currency(dep.amount)
                deposited_map[m_id] += dep_amt
                deposits_list_map[m_id].append({
                    "id": dep.id,
                    "amount": dep_amt,
                    "note": dep.note or "জমা",
                    "created_at": dep.created_at.isoformat(),
                })

        # 3. Fetch all expenses with paid_by and tagged_members
        expenses = list(
            Expense.objects.filter(tour_id=tour_id)
            .select_related("paid_by")
            .prefetch_related("tagged_members")
            .order_by("created_at")
        )

        for expense in expenses:
            exp_amt = round_currency(expense.amount)

            # Credit member who paid out-of-pocket
            if expense.paid_by_id and expense.paid_by_id in out_of_pocket_map:
                out_of_pocket_map[expense.paid_by_id] += exp_amt
                paid_expenses_map[expense.paid_by_id].append({
                    "id": expense.id,
                    "purpose": expense.purpose,
                    "amount": exp_amt,
                    "note": getattr(expense, "note", "") or "",
                    "created_at": expense.created_at.isoformat(),
                })

            tagged = list(expense.tagged_members.all())
            is_split_all = getattr(expense, "split_all", True)
            if is_split_all or not tagged:
                target_member_ids = all_member_ids
            else:
                target_member_ids = [tm.id for tm in tagged if tm.id in member_lookup]

            if not target_member_ids:
                continue

            num_targets = Decimal(len(target_member_ids))
            per_head_share = round_currency(exp_amt / num_targets)

            payer_title = expense.paid_by.name if expense.paid_by else "Common Fund"

            for target_id in target_member_ids:
                allocated_expense_map[target_id] += per_head_share
                consumed_expenses_map[target_id].append({
                    "id": expense.id,
                    "purpose": expense.purpose,
                    "total_amount": exp_amt,
                    "my_share": per_head_share,
                    "paid_by": payer_title,
                    "note": getattr(expense, "note", "") or "",
                    "created_at": expense.created_at.isoformat(),
                })

        # 4. Compile final settlement records
        settlement_results = []
        for member in members:
            m_id = member.id
            deposited = round_currency(deposited_map[m_id])
            out_of_pocket = round_currency(out_of_pocket_map[m_id])
            allocated = round_currency(allocated_expense_map[m_id])
            net_balance = round_currency((deposited + out_of_pocket) - allocated)

            if net_balance > ZERO_CURRENCY:
                status = "REFUNDABLE"
            elif net_balance < ZERO_CURRENCY:
                status = "PAYABLE"
            else:
                status = "SETTLED"

            settlement_results.append({
                "member_id": member.id,
                "name": member.name,
                "email": member.email,
                "role": member.role,
                "designation": getattr(member, "designation", "") or "",
                "total_deposited": deposited,
                "out_of_pocket_paid": out_of_pocket,
                "allocated_expense": allocated,
                "net_balance": net_balance,
                "status": status,
                "deposits_list": deposits_list_map[m_id],
                "paid_expenses_list": paid_expenses_map[m_id],
                "consumed_expenses_list": consumed_expenses_map[m_id],
            })

        # In-memory financial summary from already fetched records (0ms, 0 extra queries)
        total_credit = round_currency(sum((dep.amount for dep in all_deposits), ZERO_CURRENCY))
        total_debit = round_currency(sum((exp.amount for exp in expenses), ZERO_CURRENCY))
        remaining_balance = round_currency(total_credit - total_debit)

        budget_progress: Optional[Decimal] = None
        if tour.budget_limit and tour.budget_limit > ZERO_CURRENCY:
            raw_progress = (total_debit / tour.budget_limit) * Decimal("100.00")
            budget_progress = round_currency(raw_progress)

        return {
            "tour_id": tour.id,
            "tour_title": tour.title,
            "total_credit": total_credit,
            "total_debit": total_debit,
            "remaining_balance": remaining_balance,
            "budget_limit": tour.budget_limit,
            "budget_progress": budget_progress,
            "members": settlement_results,
        }

    @staticmethod
    def record_activity(
        tour_id: UUID,
        actor: Any,
        action: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> ActivityLog:
        return ActivityLog.objects.create(
            tour_id=tour_id,
            actor=actor if actor and getattr(actor, "is_authenticated", False) else None,
            action=action,
            details=details or {},
        )
