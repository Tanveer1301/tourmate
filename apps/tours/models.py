import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class Tour(models.Model):
    """
    Core trip container representing a shared tour and expense pool.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, help_text="Tour title (e.g., 'Sajek Valley Expedition 2026')")
    description = models.TextField(blank=True, default="", help_text="Trip itinerary or general notes")
    color_theme = models.CharField(max_length=50, default="#3B82F6", help_text="Hex color code or theme preset")
    budget_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Optional max budget ceiling for tracking progress",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tours",
        help_text="User who initiated this tour",
    )
    is_archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tours"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_by", "is_archived"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return self.title


class TourMember(models.Model):
    """
    Participant in a tour. Can be linked to an existing registered User,
    or exist as an unlinked named member (e.g., invited offline or pending sign-up).
    """
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        EDITOR = "EDITOR", "Editor"
        COMMENTER = "COMMENTER", "Commenter"
        VIEWER = "VIEWER", "Viewer"

    tour = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tour_memberships",
    )
    name = models.CharField(max_length=150, help_text="Display name for settlements and tags")
    email = models.EmailField(max_length=255, null=True, blank=True, help_text="Email for invitation and matching")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EDITOR)
    designation = models.CharField(max_length=100, blank=True, default="", help_text="Custom or fun designation/title")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tour_members"
        ordering = ["joined_at"]
        constraints = [
            # Ensure unique email within a tour when email is provided
            models.UniqueConstraint(
                fields=["tour", "email"],
                condition=Q(email__isnull=False) & ~Q(email=""),
                name="unique_tour_member_email",
            ),
            # Ensure a user is added only once per tour
            models.UniqueConstraint(
                fields=["tour", "user"],
                condition=Q(user__isnull=False),
                name="unique_tour_member_user",
            ),
        ]
        indexes = [
            models.Index(fields=["tour", "role"]),
            models.Index(fields=["tour", "email"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.role}) in {self.tour.title}"


class Deposit(models.Model):
    """
    A member's contribution to the Tour's Common Fund (Deposit).
    Increases the Tour's available pool balance and member's credit.
    """
    tour = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="deposits")
    member = models.ForeignKey(TourMember, on_delete=models.CASCADE, related_name="deposits")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Deposit contribution value",
    )
    note = models.CharField(max_length=255, blank=True, default="", help_text="Optional memo (e.g. Bank transfer ref)")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tour_deposits"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tour", "created_at"]),
            models.Index(fields=["member", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.member.name} deposited {self.amount} to {self.tour.title}"


class Expense(models.Model):
    """
    An expense incurred during the tour.
    - If `paid_by` is NULL: Paid directly from the Common Fund.
    - If `paid_by` is set: Paid out-of-pocket by that specific TourMember.
    - `tagged_members`: The members sharing this expense. If empty, the expense
      is automatically split evenly among ALL active tour members.
    """
    tour = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="expenses")
    purpose = models.CharField(max_length=255, db_index=True, help_text="Expense purpose / category (e.g., Dinner, Fuel, Hotel)")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Total expense amount",
    )
    paid_by = models.ForeignKey(
        TourMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_expenses",
        help_text="Member who paid out-of-pocket. NULL indicates payment from Common Fund.",
    )
    tagged_members = models.ManyToManyField(
        TourMember,
        related_name="tagged_expenses",
        blank=True,
        help_text="Members sharing this expense. If empty, split among all tour members.",
    )
    split_all = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True if split equally among all current and future tour members. If False, split only among tagged_members.",
    )
    receipt_image = models.URLField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Receipt image URL or cloud storage link",
    )
    note = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Optional remarks or memo",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_expenses",
        help_text="User who logged this expense entry",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tour_expenses"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tour", "created_at"]),
            models.Index(fields=["purpose", "created_at"]),
            models.Index(fields=["paid_by"]),
        ]

    def __str__(self) -> str:
        return f"{self.purpose} ({self.amount}) in {self.tour.title}"


class ActivityLog(models.Model):
    """
    Audit log of actions performed within a tour for real-time mobile feed.
    """
    tour = models.ForeignKey(Tour, on_delete=models.CASCADE, related_name="activity_logs")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    action = models.CharField(max_length=100, help_text="Action descriptor (e.g. 'CREATED_EXPENSE', 'DEPOSIT_ADDED')")
    details = models.JSONField(default=dict, blank=True, help_text="Structured snapshot of changed data")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tour_activity_logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["tour", "timestamp"]),
        ]

    def __str__(self) -> str:
        actor_name = self.actor.email if self.actor else "System"
        return f"[{self.timestamp}] {actor_name}: {self.action}"


class ExpenseComment(models.Model):
    """
    Collaborative discussion thread attached to individual expenses.
    """
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="expense_comments",
    )
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tour_expense_comments"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["expense", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Comment by {self.author.email} on {self.expense.purpose}"


class Feedback(models.Model):
    """
    User suggestion or complaint submitted to tour managers / administrators.
    """
    class FeedbackType(models.TextChoices):
        SUGGESTION = "SUGGESTION", "Suggestion"
        COMPLAINT = "COMPLAINT", "Complaint"

    class FeedbackStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feedbacks",
    )
    user_name = models.CharField(max_length=255)
    user_email = models.EmailField()
    feedback_type = models.CharField(
        max_length=20,
        choices=FeedbackType.choices,
        default=FeedbackType.SUGGESTION,
    )
    message = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=FeedbackStatus.choices,
        default=FeedbackStatus.PENDING,
        db_index=True,
    )
    admin_reply = models.TextField(blank=True, default="")
    replied_at = models.DateTimeField(null=True, blank=True)
    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replied_feedbacks",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tour_feedbacks"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["feedback_type", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.feedback_type}] {self.user_name} ({self.user_email}): {self.message[:30]}"


class SiteConfig(models.Model):
    """
    Singleton configuration model for No-Code Site Customizer (Appearance & CMS).
    Allows modifying branding, live texts, color theme presets, member designations,
    and scheduled global pop-up announcements without code redeployments.
    """
    key = models.CharField(max_length=50, unique=True, default="default")

    # Live Text & Language CMS
    app_name = models.CharField(max_length=100, default="TourMate")
    slogan_bn = models.CharField(max_length=255, default="ট্যুর হোক সহজ, হিসাব থাকুক নির্ভুল")
    slogan_en = models.CharField(max_length=255, default="Smart Tour Expense Tracker")
    welcome_title_bn = models.CharField(max_length=255, default="স্বাগতম")
    welcome_title_en = models.CharField(max_length=255, default="Welcome")
    welcome_msg_bn = models.TextField(blank=True, default="বন্ধুদের সাথে ট্যুরের কমন ফান্ড ও খরচের নির্ভুল হিসাব রাখুন সহজে।")
    welcome_msg_en = models.TextField(blank=True, default="Track group tour expenses, deposits, and split settlements effortlessly.")
    footer_text_bn = models.CharField(max_length=255, default="TourMate - ট্যুর হোক সহজ, হিসাব থাকুক নির্ভুল")
    footer_text_en = models.CharField(max_length=255, default="TourMate - Smart Tour Expense Tracker")

    # Colors & Theme Customizer
    primary_color = models.CharField(max_length=20, default="#2563EB")
    bg_shade = models.CharField(max_length=20, default="#F8FAFC")
    custom_themes = models.JSONField(
        default=list,
        blank=True,
        help_text="Available tour color palette hex codes"
    )
    custom_designations = models.JSONField(
        default=list,
        blank=True,
        help_text="Available fun member designations"
    )

    # Global Announcement Pop-up
    announcement_enabled = models.BooleanField(default=False)
    announcement_id = models.CharField(max_length=50, default="announcement-1")
    announcement_title_bn = models.CharField(max_length=255, blank=True, default="")
    announcement_title_en = models.CharField(max_length=255, blank=True, default="")
    announcement_msg_bn = models.TextField(blank=True, default="")
    announcement_msg_en = models.TextField(blank=True, default="")
    announcement_start = models.DateTimeField(null=True, blank=True)
    announcement_end = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "site_config"
        verbose_name = "Site Configuration"

    def __str__(self) -> str:
        return f"Site Configuration ({self.app_name})"

    @classmethod
    def get_solo(cls):
        default_themes = ["#2563EB", "#059669", "#E11D48", "#D97706", "#7C3AED", "#0891B2", "#4F46E5"]
        default_designations = [
            "ক্যাশিয়ার / হিসাবরক্ষক",
            "ট্যুর লিডার",
            "ট্যুর ম্যানেজার",
            "ভোজনরসিক / খাদক",
            "অফিসিয়াল ফটোগ্রাফার",
            "ন্যাভিগেটর / দিকনির্দেশক",
            "ডিজে / এন্টারটেইনার",
            "দোকানদার পার্টনার",
        ]
        obj, created = cls.objects.get_or_create(
            key="default",
            defaults={
                "custom_themes": default_themes,
                "custom_designations": default_designations,
            }
        )
        if not obj.custom_themes:
            obj.custom_themes = default_themes
            obj.save(update_fields=["custom_themes"])
        if not obj.custom_designations:
            obj.custom_designations = default_designations
            obj.save(update_fields=["custom_designations"])
        return obj


