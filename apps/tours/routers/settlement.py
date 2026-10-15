from uuid import UUID

from ninja import Router

from apps.tours.models import TourMember
from apps.tours.permissions import require_tour_access
from apps.tours.schemas import ErrorOut, SettlementBalanceSheetOut
from apps.tours.services.settlement import SettlementService

router = Router(tags=["Settlement"])


@router.get(
    "/{tour_id}/settlement",
    response={200: SettlementBalanceSheetOut, 403: ErrorOut, 404: ErrorOut},
    summary="Get complete tour settlement balance sheet",
)
def get_tour_settlement(request, tour_id: UUID):
    """
    Returns the final automated settlement sheet for the tour.
    For each member:
    - total_deposited: Funds contributed to the Common Pool.
    - out_of_pocket_paid: Expenses covered directly by the member.
    - allocated_expense: Fair share of all tagged or general expenses.
    - net_balance: (deposited + out_of_pocket) - allocated_expense.
    - status: 'REFUNDABLE' (>0), 'PAYABLE' (<0), or 'SETTLED' (==0).
    """
    tour, _ = require_tour_access(request.auth, tour_id, min_role=TourMember.Role.VIEWER)

    settlement_sheet = SettlementService.get_member_settlements(tour_id, tour=tour)
    return 200, settlement_sheet
