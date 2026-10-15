from django.contrib import admin
from apps.tours.models import (
    ActivityLog,
    Deposit,
    Expense,
    ExpenseComment,
    Feedback,
    Tour,
    TourMember,
)


class TourMemberInline(admin.TabularInline):
    model = TourMember
    extra = 1
    fields = ("name", "email", "role", "user")


@admin.register(Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ("title", "budget_limit", "color_theme", "created_by", "is_archived", "created_at")
    list_filter = ("is_archived", "created_at", "color_theme")
    search_fields = ("title", "description", "created_by__email")
    inlines = [TourMemberInline]
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(TourMember)
class TourMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "tour", "email", "role", "user", "joined_at")
    list_filter = ("role", "tour", "joined_at")
    search_fields = ("name", "email", "tour__title")


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("tour", "member", "amount", "note", "created_at")
    list_filter = ("tour", "created_at")
    search_fields = ("member__name", "note", "tour__title")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("purpose", "tour", "amount", "paid_by", "created_by", "created_at")
    list_filter = ("tour", "created_at")
    search_fields = ("purpose", "tour__title", "paid_by__name")
    filter_horizontal = ("tagged_members",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("action", "tour", "actor", "timestamp")
    list_filter = ("tour", "action", "timestamp")
    search_fields = ("action", "tour__title", "actor__email")
    readonly_fields = ("timestamp",)


@admin.register(ExpenseComment)
class ExpenseCommentAdmin(admin.ModelAdmin):
    list_display = ("expense", "author", "created_at")
    list_filter = ("created_at",)
    search_fields = ("comment", "author__email", "expense__purpose")


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("feedback_type", "user_name", "user_email", "message", "created_at")
    list_filter = ("feedback_type", "created_at")
    search_fields = ("user_name", "user_email", "message")
    readonly_fields = ("created_at",)

