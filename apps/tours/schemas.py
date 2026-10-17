from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from ninja import Field, Schema
from pydantic import field_validator


# ---------------------------------------------------------------------------
# Generic / Common Schemas
# ---------------------------------------------------------------------------

class ErrorOut(Schema):
    detail: str


class SuccessOut(Schema):
    success: bool = True
    message: str = "Operation completed successfully."


# ---------------------------------------------------------------------------
# Auth & User Schemas
# ---------------------------------------------------------------------------

class GoogleAuthIn(Schema):
    id_token: str = Field(..., description="Google OAuth2 ID Token from client authentication")


class UserOut(Schema):
    id: int
    email: str
    first_name: str
    last_name: str
    avatar_url: Optional[str] = None
    admin_role: str = "NONE"
    is_staff: bool = False
    is_superuser: bool = False



class AuthTokenOut(Schema):
    access_token: str
    token_type: str = "Bearer"
    user: UserOut


class ProfileUpdateIn(Schema):
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None



# ---------------------------------------------------------------------------
# Tour Member Schemas
# ---------------------------------------------------------------------------

class TourMemberOut(Schema):
    id: int
    name: str
    email: Optional[str] = None
    role: str
    designation: Optional[str] = ""
    joined_at: datetime
    user_id: Optional[int] = None


class DepositItemOut(Schema):
    id: int
    amount: Decimal
    note: str
    created_at: datetime


class TourMemberDepositOut(Schema):
    member: TourMemberOut
    total_deposited: Decimal = Decimal("0.00")
    deposits: List[DepositItemOut] = []
    breakdown_str: str = ""


class TourMemberUpdateIn(Schema):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    designation: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            valid_roles = {"OWNER", "EDITOR", "COMMENTER", "VIEWER"}
            upper = v.upper()
            if upper not in valid_roles:
                raise ValueError(f"Role must be one of {valid_roles}")
            return upper
        return v


class TourShareIn(Schema):
    email: Optional[str] = None
    name: Optional[str] = None
    role: str = "EDITOR"
    designation: Optional[str] = ""

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid_roles = {"OWNER", "EDITOR", "COMMENTER", "VIEWER"}
        upper = v.upper()
        if upper not in valid_roles:
            raise ValueError(f"Role must be one of {valid_roles}")
        return upper


# ---------------------------------------------------------------------------
# Tour Schemas
# ---------------------------------------------------------------------------

class TourCreateIn(Schema):
    title: str = Field(..., max_length=255)
    description: Optional[str] = ""
    color_theme: str = "#3B82F6"
    budget_limit: Optional[Decimal] = None

    @field_validator("budget_limit")
    @classmethod
    def validate_budget(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= Decimal("0.00"):
            raise ValueError("budget_limit must be greater than zero.")
        return v


class TourUpdateIn(Schema):
    title: Optional[str] = None
    description: Optional[str] = None
    color_theme: Optional[str] = None
    budget_limit: Optional[Decimal] = None
    clear_budget: Optional[bool] = False
    is_archived: Optional[bool] = None


class TourDetailOut(Schema):
    id: UUID
    title: str
    description: str
    color_theme: str
    budget_limit: Optional[Decimal] = None
    created_by: UserOut
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class TourListOut(Schema):
    id: UUID
    title: str
    description: Optional[str] = ""
    color_theme: str
    budget_limit: Optional[Decimal] = None
    is_archived: bool
    total_credit: Decimal = Decimal("0.00")
    total_debit: Decimal = Decimal("0.00")
    remaining_balance: Decimal = Decimal("0.00")
    members_count: int = 0
    created_at: datetime


class TourSummaryOut(Schema):
    total_credit: Decimal
    total_debit: Decimal
    remaining_balance: Decimal
    budget_limit: Optional[Decimal] = None
    budget_progress: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# Deposit Schemas
# ---------------------------------------------------------------------------

class DepositCreateIn(Schema):
    member_id: int
    amount: Decimal = Field(..., gt=Decimal("0.00"))
    note: Optional[str] = ""


class DepositUpdateIn(Schema):
    amount: Optional[Decimal] = None
    note: Optional[str] = None


class DepositOut(Schema):
    id: int
    tour_id: UUID
    member: TourMemberOut
    amount: Decimal
    note: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Expense Schemas
# ---------------------------------------------------------------------------

class ExpenseCreateIn(Schema):
    purpose: str = Field(..., max_length=255)
    amount: Decimal = Field(..., gt=Decimal("0.00"))
    paid_by_id: Optional[int] = Field(
        None,
        description="ID of the TourMember who paid out-of-pocket. Omit or NULL for Common Fund.",
    )
    tagged_member_ids: Optional[List[int]] = Field(
        default=None,
        description="IDs of members who share this expense. If empty or None, splits across ALL members.",
    )
    split_all: Optional[bool] = None
    note: Optional[str] = ""
    receipt_image: Optional[str] = ""


class ExpenseUpdateIn(Schema):
    purpose: Optional[str] = None
    amount: Optional[Decimal] = None
    paid_by_id: Optional[int] = None
    tagged_member_ids: Optional[List[int]] = None
    split_all: Optional[bool] = None
    note: Optional[str] = None
    receipt_image: Optional[str] = None


class ExpenseOut(Schema):
    id: int
    tour_id: UUID
    purpose: str
    amount: Decimal
    paid_by: Optional[TourMemberOut] = None
    tagged_members: List[TourMemberOut]
    split_all: bool = True
    note: str = ""
    receipt_image: str
    created_by: UserOut
    created_at: datetime
    comments_count: int = 0


class ExpenseSuggestionsOut(Schema):
    my_recent: List[str]
    global_popular: List[str]


# ---------------------------------------------------------------------------
# Settlement Schemas
# ---------------------------------------------------------------------------

class MemberSettlementOut(Schema):
    member_id: int
    name: str
    email: Optional[str] = None
    role: str
    designation: Optional[str] = ""
    total_deposited: Decimal
    out_of_pocket_paid: Decimal
    allocated_expense: Decimal
    net_balance: Decimal
    status: str  # "REFUNDABLE" | "PAYABLE" | "SETTLED"
    deposits_list: List[Dict[str, Any]] = []
    paid_expenses_list: List[Dict[str, Any]] = []
    consumed_expenses_list: List[Dict[str, Any]] = []


class SettlementBalanceSheetOut(Schema):
    tour_id: UUID
    tour_title: str
    total_credit: Decimal
    total_debit: Decimal
    remaining_balance: Decimal
    budget_limit: Optional[Decimal] = None
    budget_progress: Optional[Decimal] = None
    members: List[MemberSettlementOut]


# ---------------------------------------------------------------------------
# Collaboration & Activity Schemas
# ---------------------------------------------------------------------------

class ExpenseCommentIn(Schema):
    comment: str = Field(..., min_length=1)


class ExpenseCommentOut(Schema):
    id: int
    expense_id: int
    author: UserOut
    comment: str
    created_at: datetime


class ActivityLogOut(Schema):
    id: int
    action: str
    actor: Optional[UserOut] = None
    details: Dict[str, Any]
    timestamp: datetime


# ---------------------------------------------------------------------------
# Dashboard Schema (Aggregated for Mobile)
# ---------------------------------------------------------------------------

class TourDashboardOut(Schema):
    tour: TourDetailOut
    summary: TourSummaryOut
    members: List[TourMemberDepositOut]
    recent_expenses: List[ExpenseOut]


# ---------------------------------------------------------------------------
# Feedback / Suggestion Schema
# ---------------------------------------------------------------------------

class FeedbackIn(Schema):
    feedback_type: str = "SUGGESTION"  # 'SUGGESTION' or 'COMPLAINT'
    message: str


class FeedbackOut(Schema):
    id: int
    user_name: str
    user_email: str
    feedback_type: str
    message: str
    status: str = "PENDING"
    admin_reply: str = ""
    replied_at: Optional[datetime] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Admin Console Schemas
# ---------------------------------------------------------------------------

class AdminMetricsOut(Schema):
    users_total: int
    users_today: int
    users_month: int
    users_year: int
    users_inactive: int
    tours_total: int
    tours_active: int
    tours_archived: int
    total_deposits_volume: Decimal
    total_expenses_volume: Decimal
    feedbacks_pending: int
    feedbacks_resolved: int


class AdminUserOut(Schema):
    id: int
    email: str
    full_name: str
    first_name: str
    last_name: str
    avatar_url: Optional[str] = None
    admin_role: str
    is_active: bool
    is_staff: bool
    is_superuser: bool
    date_joined: datetime
    tours_created_count: int = 0
    tours_joined_count: int = 0


class AdminUserRoleIn(Schema):
    admin_role: str


class AdminUserStatusIn(Schema):
    is_active: bool


class AdminTourOut(Schema):
    id: UUID
    title: str
    description: str
    color_theme: str
    budget_limit: Optional[Decimal] = None
    is_archived: bool
    created_at: datetime
    created_by_email: str
    created_by_name: str
    members_count: int
    total_deposits: Decimal
    total_expenses: Decimal
    fund_balance: Decimal


class AdminTourUpdateIn(Schema):
    title: Optional[str] = None
    description: Optional[str] = None
    color_theme: Optional[str] = None
    budget_limit: Optional[Decimal] = None
    is_archived: Optional[bool] = None


class SiteConfigOut(Schema):
    app_name: str
    slogan_bn: str
    slogan_en: str
    welcome_title_bn: str
    welcome_title_en: str
    welcome_msg_bn: str
    welcome_msg_en: str
    footer_text_bn: str
    footer_text_en: str
    primary_color: str
    bg_shade: str
    custom_themes: List[str]
    custom_designations: List[str]
    announcement_enabled: bool
    announcement_id: str
    announcement_title_bn: str
    announcement_title_en: str
    announcement_msg_bn: str
    announcement_msg_en: str
    announcement_start: Optional[datetime] = None
    announcement_end: Optional[datetime] = None
    updated_at: datetime


class SiteConfigIn(Schema):
    app_name: Optional[str] = None
    slogan_bn: Optional[str] = None
    slogan_en: Optional[str] = None
    welcome_title_bn: Optional[str] = None
    welcome_title_en: Optional[str] = None
    welcome_msg_bn: Optional[str] = None
    welcome_msg_en: Optional[str] = None
    footer_text_bn: Optional[str] = None
    footer_text_en: Optional[str] = None
    primary_color: Optional[str] = None
    bg_shade: Optional[str] = None
    custom_themes: Optional[List[str]] = None
    custom_designations: Optional[List[str]] = None
    announcement_enabled: Optional[bool] = None
    announcement_id: Optional[str] = None
    announcement_title_bn: Optional[str] = None
    announcement_title_en: Optional[str] = None
    announcement_msg_bn: Optional[str] = None
    announcement_msg_en: Optional[str] = None
    announcement_start: Optional[datetime] = None
    announcement_end: Optional[datetime] = None


class AdminFeedbackOut(Schema):
    id: int
    user_id: Optional[int] = None
    user_name: str
    user_email: str
    feedback_type: str
    message: str
    status: str
    admin_reply: str
    replied_at: Optional[datetime] = None
    replied_by_name: Optional[str] = None
    created_at: datetime


class AdminFeedbackReplyIn(Schema):
    reply: str
    status: Optional[str] = "RESOLVED"


