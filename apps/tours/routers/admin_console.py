import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone as django_tz
from ninja import Query, Router
from ninja.errors import HttpError

from apps.accounts.models import AdminRole
from apps.accounts.security import JWTAuth
from apps.tours.models import Deposit, Expense, Feedback, SiteConfig, Tour, TourMember
from apps.tours.schemas import (
    AdminFeedbackOut,
    AdminFeedbackReplyIn,
    AdminFeedbackUpdateIn,
    AdminMetricsOut,
    AdminTourOut,
    AdminTourUpdateIn,
    AdminUserOut,
    AdminUserRoleIn,
    AdminUserStatusIn,
    ErrorOut,
    SiteConfigIn,
    SiteConfigOut,
    SuccessOut,
)

logger = logging.getLogger(__name__)
User = get_user_model()

router = Router(tags=["Admin Console"], auth=JWTAuth())
public_router = Router(tags=["Public Config"], auth=None)


def _get_admin_user(request) -> Any:
    user = request.auth
    if not user:
        raise HttpError(401, "লগইন করা আবশ্যক (Authentication required).")
    
    # Auto-ensure super admin if email in SUPER_ADMIN_EMAILS
    super_admin_emails = getattr(settings, "SUPER_ADMIN_EMAILS", [])
    if user.email and user.email.lower() in super_admin_emails:
        if user.admin_role != AdminRole.SUPER_ADMIN or not user.is_staff or not user.is_superuser:
            user.admin_role = AdminRole.SUPER_ADMIN
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["admin_role", "is_staff", "is_superuser"])

    if not user.is_any_admin:
        raise HttpError(403, "অ্যাডমিন অ্যাক্সেস নেই (Admin access required).")
    return user


def _ensure_super_admin(user: Any) -> None:
    if not user.is_super_admin:
        raise HttpError(403, "এই কাজের জন্য শুধুমাত্র Super Admin এর অনুমতি রয়েছে।")


def _ensure_can_manage_cms(user: Any) -> None:
    if user.admin_role not in {AdminRole.SUPER_ADMIN, AdminRole.CONTENT_MANAGER} and not user.is_superuser:
        raise HttpError(403, "শুধুমাত্র Super Admin বা UI & Content Manager সাইট কনফিগারেশন পরিবর্তন করতে পারেন।")


def _ensure_can_manage_feedback(user: Any) -> None:
    if user.admin_role not in {AdminRole.SUPER_ADMIN, AdminRole.SUB_ADMIN, AdminRole.SUPPORT} and not user.is_superuser:
        raise HttpError(403, "শুধুমাত্র Support বা Admin টিম অভিযোগ ও পরামর্শ ডেস্কে অ্যাক্সেস করতে পারেন।")


def _ensure_can_moderate(user: Any) -> None:
    if user.admin_role not in {AdminRole.SUPER_ADMIN, AdminRole.SUB_ADMIN} and not user.is_superuser:
        raise HttpError(403, "শুধুমাত্র Super Admin বা Sub-Admin/Moderator এই কাজটি করতে পারেন।")


# ---------------------------------------------------------------------------
# 1. Admin Profile & Session
# ---------------------------------------------------------------------------

@router.get("/me", summary="Get authenticated admin status and capabilities")
def get_admin_me(request):
    admin = _get_admin_user(request)
    return {
        "id": admin.id,
        "email": admin.email,
        "name": admin.full_name,
        "avatar_url": admin.avatar_url,
        "admin_role": admin.admin_role,
        "is_super_admin": admin.is_super_admin,
        "is_sub_admin": admin.admin_role == AdminRole.SUB_ADMIN,
        "is_content_manager": admin.admin_role == AdminRole.CONTENT_MANAGER,
        "is_support": admin.admin_role == AdminRole.SUPPORT,
        "can_manage_users": admin.is_super_admin,
        "can_manage_cms": admin.is_super_admin or admin.admin_role == AdminRole.CONTENT_MANAGER,
        "can_manage_feedback": admin.is_super_admin or admin.admin_role in {AdminRole.SUB_ADMIN, AdminRole.SUPPORT},
        "can_moderate_tours": admin.is_super_admin or admin.admin_role == AdminRole.SUB_ADMIN,
    }


# ---------------------------------------------------------------------------
# 2. Top Metrics & Summary Cards
# ---------------------------------------------------------------------------

@router.get("/metrics", response={200: AdminMetricsOut}, summary="Live platform metrics for Overview tab")
def get_metrics(request):
    _get_admin_user(request)
    now = django_tz.now()

    # User stats
    users_total = User.objects.count()
    users_today = User.objects.filter(
        date_joined__year=now.year,
        date_joined__month=now.month,
        date_joined__day=now.day,
    ).count()
    users_month = User.objects.filter(
        date_joined__year=now.year,
        date_joined__month=now.month,
    ).count()
    users_year = User.objects.filter(
        date_joined__year=now.year,
    ).count()
    users_inactive = User.objects.filter(is_active=False).count()

    # Tour stats
    tours_total = Tour.objects.count()
    tours_active = Tour.objects.filter(is_archived=False).count()
    tours_archived = Tour.objects.filter(is_archived=True).count()

    # Volume stats
    dep_agg = Deposit.objects.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    exp_agg = Expense.objects.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    # Feedback stats
    feedbacks_pending = Feedback.objects.filter(status=Feedback.FeedbackStatus.PENDING).count()
    feedbacks_resolved = Feedback.objects.filter(status=Feedback.FeedbackStatus.RESOLVED).count()

    return 200, {
        "users_total": users_total,
        "users_today": users_today,
        "users_month": users_month,
        "users_year": users_year,
        "users_inactive": users_inactive,
        "tours_total": tours_total,
        "tours_active": tours_active,
        "tours_archived": tours_archived,
        "total_deposits_volume": dep_agg,
        "total_expenses_volume": exp_agg,
        "feedbacks_pending": feedbacks_pending,
        "feedbacks_resolved": feedbacks_resolved,
    }


# ---------------------------------------------------------------------------
# 3. User & Role Management
# ---------------------------------------------------------------------------

@router.get("/users", response={200: List[AdminUserOut]}, summary="List and search platform users")
def list_users(
    request,
    search: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    activity: Optional[str] = None,
    limit: int = 150,
):
    _get_admin_user(request)
    qs = User.objects.all().order_by("-date_joined")

    if search:
        s = search.strip()
        qs = qs.filter(
            Q(email__icontains=s)
            | Q(first_name__icontains=s)
            | Q(last_name__icontains=s)
        )

    if role and role != "ALL":
        qs = qs.filter(admin_role=role)

    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)

    now = django_tz.now()
    if activity == "active_7d":
        seven_days_ago = now - timedelta(days=7)
        qs = qs.filter(last_login__gte=seven_days_ago)
    elif activity == "inactive_7d":
        seven_days_ago = now - timedelta(days=7)
        qs = qs.filter(
            Q(last_login__lt=seven_days_ago)
            | (Q(last_login__isnull=True) & Q(date_joined__lt=seven_days_ago))
        )
    elif activity == "inactive_30d":
        thirty_days_ago = now - timedelta(days=30)
        qs = qs.filter(
            Q(last_login__lt=thirty_days_ago)
            | (Q(last_login__isnull=True) & Q(date_joined__lt=thirty_days_ago))
        )
    elif activity == "never":
        qs = qs.filter(last_login__isnull=True)

    users_slice = list(qs[:limit])

    user_ids = [u.id for u in users_slice]
    # Fetch tour counts
    created_counts = dict(
        Tour.objects.filter(created_by_id__in=user_ids)
        .values("created_by_id")
        .annotate(cnt=Count("id"))
        .values_list("created_by_id", "cnt")
    )
    joined_counts = dict(
        TourMember.objects.filter(user_id__in=user_ids)
        .values("user_id")
        .annotate(cnt=Count("id"))
        .values_list("user_id", "cnt")
    )

    out = []
    for u in users_slice:
        out.append(
            AdminUserOut(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                first_name=u.first_name,
                last_name=u.last_name,
                avatar_url=u.avatar_url or None,
                admin_role=u.admin_role,
                is_active=u.is_active,
                is_staff=u.is_staff,
                is_superuser=u.is_superuser,
                date_joined=u.date_joined,
                last_login=u.last_login,
                tours_created_count=created_counts.get(u.id, 0),
                tours_joined_count=joined_counts.get(u.id, 0),
            )
        )
    return 200, out


@router.put("/users/{user_id}/role", response={200: AdminUserOut, 400: ErrorOut, 403: ErrorOut}, summary="Change a user's admin role")
def update_user_role(request, user_id: int, payload: AdminUserRoleIn):
    admin = _get_admin_user(request)
    _ensure_super_admin(admin)

    target_user = User.objects.filter(pk=user_id).first()
    if not target_user:
        raise HttpError(404, "ইউজার পাওয়া যায়নি (User not found).")

    new_role = payload.admin_role.upper().strip()
    valid_roles = {choice[0] for choice in AdminRole.choices}
    if new_role not in valid_roles:
        raise HttpError(400, f"অবৈধ রোল। প্রযোজ্য রোলসমূহ: {', '.join(valid_roles)}")

    # Guard: .env super admin backup protection
    super_admin_emails = getattr(settings, "SUPER_ADMIN_EMAILS", [])
    if target_user.email.lower() in super_admin_emails and new_role != AdminRole.SUPER_ADMIN:
        raise HttpError(403, "এই ইমেইলটি .env ফাইলে Super Admin হিসেবে সুরক্ষিত রয়েছে। এর রোল পরিবর্তন করা যাবে না।")

    # Guard: prevent self-demotion if caller is demoting themselves
    if target_user.id == admin.id and new_role != AdminRole.SUPER_ADMIN:
        # Check if there is at least one other active super admin
        other_super = User.objects.filter(admin_role=AdminRole.SUPER_ADMIN, is_active=True).exclude(pk=admin.id).exists()
        if not other_super:
            raise HttpError(403, "আপনি প্ল্যাটফর্মের একমাত্র Super Admin। নিজেকে ডিমোট করতে পারবেন না।")

    target_user.admin_role = new_role
    target_user.is_staff = new_role != AdminRole.NONE
    if new_role == AdminRole.SUPER_ADMIN:
        target_user.is_superuser = True
    elif target_user.is_superuser and target_user.email.lower() not in super_admin_emails:
        target_user.is_superuser = False

    target_user.save(update_fields=["admin_role", "is_staff", "is_superuser"])

    created_cnt = Tour.objects.filter(created_by=target_user).count()
    joined_cnt = TourMember.objects.filter(user=target_user).count()

    return 200, AdminUserOut(
        id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        first_name=target_user.first_name,
        last_name=target_user.last_name,
        avatar_url=target_user.avatar_url or None,
        admin_role=target_user.admin_role,
        is_active=target_user.is_active,
        is_staff=target_user.is_staff,
        is_superuser=target_user.is_superuser,
        date_joined=target_user.date_joined,
        tours_created_count=created_cnt,
        tours_joined_count=joined_cnt,
    )


@router.put("/users/{user_id}/status", response={200: SuccessOut, 403: ErrorOut}, summary="Block or unblock a user")
def update_user_status(request, user_id: int, payload: AdminUserStatusIn):
    admin = _get_admin_user(request)
    _ensure_can_moderate(admin)

    target_user = User.objects.filter(pk=user_id).first()
    if not target_user:
        raise HttpError(404, "ইউজার পাওয়া যায়নি (User not found).")

    # Sub-admin cannot block a Super Admin
    if target_user.is_super_admin and not admin.is_super_admin:
        raise HttpError(403, "Sub-Admin কোনো Super Admin কে ব্লক করতে পারবেন না।")

    # Caller cannot block themselves
    if target_user.id == admin.id:
        raise HttpError(400, "আপনি নিজের অ্যাকাউন্ট নিষ্ক্রিয় করতে পারবেন না।")

    target_user.is_active = payload.is_active
    target_user.save(update_fields=["is_active"])

    status_str = "সক্রিয়" if payload.is_active else "ব্লক / নিষ্ক্রিয়"
    return 200, {"success": True, "message": f"ইউজার {target_user.email} সফলভাবে {status_str} করা হয়েছে।"}


# ---------------------------------------------------------------------------
# 4. Tour Explorer & God-Mode CRUD
# ---------------------------------------------------------------------------

@router.get("/tours", response={200: List[AdminTourOut]}, summary="Explore and filter all tours (God-mode)")
def list_admin_tours(
    request,
    search: Optional[str] = None,
    sort_by: str = "latest",  # latest, oldest, budget_desc, members_desc, expenses_desc
    filter_status: str = "all",  # all, active, archived
    limit: int = 100,
):
    _get_admin_user(request)
    qs = Tour.objects.select_related("created_by").prefetch_related("members", "deposits", "expenses").all()

    if search:
        s = search.strip()
        qs = qs.filter(
            Q(title__icontains=s)
            | Q(description__icontains=s)
            | Q(created_by__email__icontains=s)
            | Q(created_by__first_name__icontains=s)
            | Q(created_by__last_name__icontains=s)
        )

    if filter_status == "active":
        qs = qs.filter(is_archived=False)
    elif filter_status == "archived":
        qs = qs.filter(is_archived=True)

    if sort_by == "oldest":
        qs = qs.order_by("created_at")
    elif sort_by == "budget_desc":
        qs = qs.order_by("-budget_limit", "-created_at")
    else:
        qs = qs.order_by("-created_at")

    tours_list = list(qs[:limit])

    # Batch calculate deposits, expenses and member counts
    tour_ids = [t.id for t in tours_list]
    dep_map = dict(
        Deposit.objects.filter(tour_id__in=tour_ids)
        .values("tour_id")
        .annotate(total=Sum("amount"))
        .values_list("tour_id", "total")
    )
    exp_map = dict(
        Expense.objects.filter(tour_id__in=tour_ids)
        .values("tour_id")
        .annotate(total=Sum("amount"))
        .values_list("tour_id", "total")
    )
    mem_map = dict(
        TourMember.objects.filter(tour_id__in=tour_ids)
        .values("tour_id")
        .annotate(cnt=Count("id"))
        .values_list("tour_id", "cnt")
    )

    out = []
    for t in tours_list:
        total_dep = dep_map.get(t.id) or Decimal("0.00")
        total_exp = exp_map.get(t.id) or Decimal("0.00")
        balance = total_dep - total_exp
        members_count = mem_map.get(t.id) or 0
        creator_name = t.created_by.full_name if t.created_by else "System"

        out.append(
            AdminTourOut(
                id=t.id,
                title=t.title,
                description=t.description or "",
                color_theme=t.color_theme or "#2563EB",
                budget_limit=t.budget_limit,
                is_archived=t.is_archived,
                created_at=t.created_at,
                created_by_email=t.created_by.email if t.created_by else "",
                created_by_name=creator_name,
                members_count=members_count,
                total_deposits=total_dep,
                total_expenses=total_exp,
                fund_balance=balance,
            )
        )

    # In-memory secondary sort if requested
    if sort_by == "members_desc":
        out.sort(key=lambda x: x.members_count, reverse=True)
    elif sort_by == "expenses_desc":
        out.sort(key=lambda x: x.total_expenses, reverse=True)

    return 200, out


@router.put("/tours/{tour_id}", response={200: AdminTourOut, 400: ErrorOut, 403: ErrorOut}, summary="Edit tour metadata (God-mode)")
def update_admin_tour(request, tour_id: UUID, payload: AdminTourUpdateIn):
    admin = _get_admin_user(request)
    _ensure_can_moderate(admin)

    tour = Tour.objects.select_related("created_by").filter(id=tour_id).first()
    if not tour:
        raise HttpError(404, "ট্যুরটি খুঁজে পাওয়া যায়নি (Tour not found).")

    updates = []
    if payload.title is not None and payload.title.strip():
        tour.title = payload.title.strip()
        updates.append("title")
    if payload.description is not None:
        tour.description = payload.description.strip()
        updates.append("description")
    if payload.color_theme is not None and payload.color_theme.strip():
        tour.color_theme = payload.color_theme.strip()
        updates.append("color_theme")
    if payload.budget_limit is not None:
        tour.budget_limit = payload.budget_limit
        updates.append("budget_limit")
    if payload.is_archived is not None:
        tour.is_archived = payload.is_archived
        updates.append("is_archived")

    if updates:
        tour.save(update_fields=updates)

    dep_tot = Deposit.objects.filter(tour=tour).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    exp_tot = Expense.objects.filter(tour=tour).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    mem_cnt = TourMember.objects.filter(tour=tour).count()

    return 200, AdminTourOut(
        id=tour.id,
        title=tour.title,
        description=tour.description,
        color_theme=tour.color_theme,
        budget_limit=tour.budget_limit,
        is_archived=tour.is_archived,
        created_at=tour.created_at,
        created_by_email=tour.created_by.email if tour.created_by else "",
        created_by_name=tour.created_by.full_name if tour.created_by else "",
        members_count=mem_cnt,
        total_deposits=dep_tot,
        total_expenses=exp_tot,
        fund_balance=dep_tot - exp_tot,
    )


@router.delete("/tours/{tour_id}", response={200: SuccessOut, 403: ErrorOut}, summary="Delete a tour (God-mode)")
def delete_admin_tour(request, tour_id: UUID):
    admin = _get_admin_user(request)
    _ensure_can_moderate(admin)

    tour = Tour.objects.filter(id=tour_id).first()
    if not tour:
        raise HttpError(404, "ট্যুরটি খুঁজে পাওয়া যায়নি (Tour not found).")

    title = tour.title
    tour.delete()
    return 200, {"success": True, "message": f"ট্যুর '{title}' সফলভাবে মুছে ফেলা হয়েছে।"}


# ---------------------------------------------------------------------------
# 5. No-Code Site Customizer (Appearance & CMS)
# ---------------------------------------------------------------------------

@router.get("/config", response={200: SiteConfigOut}, summary="Get full site configuration")
def get_site_config(request):
    _get_admin_user(request)
    cfg = SiteConfig.get_solo()
    return 200, cfg


@router.put("/config", response={200: SiteConfigOut, 403: ErrorOut}, summary="Update site configuration & live texts")
def update_site_config(request, payload: SiteConfigIn):
    admin = _get_admin_user(request)
    _ensure_can_manage_cms(admin)

    cfg = SiteConfig.get_solo()
    updates = []

    fields = [
        "app_name", "slogan_bn", "slogan_en", "welcome_title_bn", "welcome_title_en",
        "welcome_msg_bn", "welcome_msg_en", "footer_text_bn", "footer_text_en",
        "primary_color", "bg_shade", "custom_themes", "custom_designations",
        "announcement_enabled", "announcement_id", "announcement_title_bn",
        "announcement_title_en", "announcement_msg_bn", "announcement_msg_en",
        "announcement_start", "announcement_end",
    ]

    for f in fields:
        val = getattr(payload, f)
        if val is not None:
            setattr(cfg, f, val)
            updates.append(f)

    if updates:
        cfg.save(update_fields=updates)

    return 200, cfg


# ---------------------------------------------------------------------------
# 6. Complaints & Suggestions Desk
# ---------------------------------------------------------------------------

@router.get("/feedbacks", response={200: List[AdminFeedbackOut]}, summary="List complaints & suggestions for admin desk")
def list_admin_feedbacks(
    request,
    feedback_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
):
    _get_admin_user(request)
    qs = Feedback.objects.select_related("user", "replied_by").all().order_by("-created_at")

    if feedback_type and feedback_type != "ALL":
        qs = qs.filter(feedback_type=feedback_type)

    if status and status != "ALL":
        qs = qs.filter(status=status)

    if search:
        s = search.strip()
        qs = qs.filter(
            Q(user_name__icontains=s)
            | Q(user_email__icontains=s)
            | Q(message__icontains=s)
            | Q(admin_reply__icontains=s)
        )

    feedbacks_list = list(qs[:limit])
    out = []
    for f in feedbacks_list:
        replied_by_name = f.replied_by.full_name if f.replied_by else None
        out.append(
            AdminFeedbackOut(
                id=f.id,
                user_id=f.user_id,
                user_name=f.user_name,
                user_email=f.user_email,
                feedback_type=f.feedback_type,
                message=f.message,
                status=f.status,
                admin_reply=f.admin_reply or "",
                replied_at=f.replied_at,
                replied_by_name=replied_by_name,
                created_at=f.created_at,
            )
        )
    return 200, out


@router.post("/feedbacks/{feedback_id}/reply", response={200: AdminFeedbackOut, 400: ErrorOut, 403: ErrorOut}, summary="Reply to user complaint or suggestion")
def reply_feedback(request, feedback_id: int, payload: AdminFeedbackReplyIn):
    admin = _get_admin_user(request)
    _ensure_can_manage_feedback(admin)

    feedback = Feedback.objects.select_related("user", "replied_by").filter(id=feedback_id).first()
    if not feedback:
        raise HttpError(404, "ফিডব্যাক পাওয়া যায়নি (Feedback not found).")

    reply_text = payload.reply.strip()
    if not reply_text:
        raise HttpError(400, "উত্তর টেক্সট খালি রাখা যাবে না (Reply cannot be empty).")

    feedback.admin_reply = reply_text
    feedback.replied_at = django_tz.now()
    feedback.replied_by = admin
    if payload.status:
        feedback.status = payload.status
    else:
        feedback.status = Feedback.FeedbackStatus.RESOLVED

    feedback.save(update_fields=["admin_reply", "replied_at", "replied_by", "status"])

    return 200, AdminFeedbackOut(
        id=feedback.id,
        user_id=feedback.user_id,
        user_name=feedback.user_name,
        user_email=feedback.user_email,
        feedback_type=feedback.feedback_type,
        message=feedback.message,
        status=feedback.status,
        admin_reply=feedback.admin_reply,
        replied_at=feedback.replied_at,
        replied_by_name=admin.full_name,
        created_at=feedback.created_at,
    )


@router.put("/feedbacks/{feedback_id}", response={200: AdminFeedbackOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut}, summary="Edit user complaint or suggestion")
def update_feedback(request, feedback_id: int, payload: AdminFeedbackUpdateIn):
    admin = _get_admin_user(request)
    _ensure_can_manage_feedback(admin)

    feedback = Feedback.objects.select_related("user", "replied_by").filter(id=feedback_id).first()
    if not feedback:
        raise HttpError(404, "ফিডব্যাক পাওয়া যায়নি (Feedback not found).")

    updates = []
    if payload.message is not None and payload.message.strip():
        feedback.message = payload.message.strip()
        updates.append("message")
    if payload.feedback_type is not None and payload.feedback_type in {Feedback.FeedbackType.SUGGESTION, Feedback.FeedbackType.COMPLAINT}:
        feedback.feedback_type = payload.feedback_type
        updates.append("feedback_type")
    if payload.status is not None and payload.status in {Feedback.FeedbackStatus.PENDING, Feedback.FeedbackStatus.RESOLVED, Feedback.FeedbackStatus.CLOSED}:
        feedback.status = payload.status
        updates.append("status")
    if payload.admin_reply is not None:
        feedback.admin_reply = payload.admin_reply.strip()
        feedback.replied_at = django_tz.now()
        feedback.replied_by = admin
        updates.extend(["admin_reply", "replied_at", "replied_by"])

    if updates:
        feedback.save(update_fields=list(set(updates)))

    replied_by_name = feedback.replied_by.full_name if feedback.replied_by else (admin.full_name if feedback.admin_reply else None)

    return 200, AdminFeedbackOut(
        id=feedback.id,
        user_id=feedback.user_id,
        user_name=feedback.user_name,
        user_email=feedback.user_email,
        feedback_type=feedback.feedback_type,
        message=feedback.message,
        status=feedback.status,
        admin_reply=feedback.admin_reply or "",
        replied_at=feedback.replied_at,
        replied_by_name=replied_by_name,
        created_at=feedback.created_at,
    )


@router.delete("/feedbacks/{feedback_id}", response={200: SuccessOut, 403: ErrorOut, 404: ErrorOut}, summary="Delete user complaint or suggestion")
def delete_feedback(request, feedback_id: int):
    admin = _get_admin_user(request)
    _ensure_can_manage_feedback(admin)

    feedback = Feedback.objects.filter(id=feedback_id).first()
    if not feedback:
        raise HttpError(404, "ফিডব্যাক পাওয়া যায়নি (Feedback not found).")

    feedback.delete()
    return 200, {"success": True, "message": "ফিডব্যাক বার্তাটি সফলভাবে ডিলিট করা হয়েছে।"}


# ---------------------------------------------------------------------------
# 7. Public Config Endpoint (Unauthenticated / Safe for all visitors)
# ---------------------------------------------------------------------------

@public_router.get("/config", summary="Public site config and active scheduled popup announcement")
def get_public_config(request):
    cfg = SiteConfig.get_solo()
    now = django_tz.now()

    # Determine if scheduled announcement is active
    announcement_active = False
    if cfg.announcement_enabled and (cfg.announcement_title_bn or cfg.announcement_title_en or cfg.announcement_msg_bn):
        time_ok = True
        if cfg.announcement_start and now < cfg.announcement_start:
            time_ok = False
        if cfg.announcement_end and now > cfg.announcement_end:
            time_ok = False
        announcement_active = time_ok

    announcement_data = None
    if announcement_active:
        announcement_data = {
            "id": cfg.announcement_id or "announcement-1",
            "title_bn": cfg.announcement_title_bn,
            "title_en": cfg.announcement_title_en,
            "msg_bn": cfg.announcement_msg_bn,
            "msg_en": cfg.announcement_msg_en,
        }

    return {
        "app_name": cfg.app_name,
        "slogan_bn": cfg.slogan_bn,
        "slogan_en": cfg.slogan_en,
        "welcome_title_bn": cfg.welcome_title_bn,
        "welcome_title_en": cfg.welcome_title_en,
        "welcome_msg_bn": cfg.welcome_msg_bn,
        "welcome_msg_en": cfg.welcome_msg_en,
        "footer_text_bn": cfg.footer_text_bn,
        "footer_text_en": cfg.footer_text_en,
        "primary_color": cfg.primary_color,
        "bg_shade": cfg.bg_shade,
        "custom_themes": cfg.custom_themes,
        "custom_designations": cfg.custom_designations,
        "announcement": announcement_data,
    }
