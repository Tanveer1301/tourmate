from datetime import datetime, timedelta, timezone
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone as django_tz

from apps.accounts.models import AdminRole, User
from apps.accounts.security import generate_access_token, provision_google_user
from apps.tours.models import Deposit, Expense, Feedback, SiteConfig, Tour, TourMember


class AdminConsoleTestCase(TestCase):
    def setUp(self):
        # Create Super Admin
        self.super_admin = User.objects.create_user(
            email="super@tourmate.test",
            first_name="Super",
            last_name="Admin",
            admin_role=AdminRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.super_token = generate_access_token(self.super_admin)

        # Create Regular User
        self.regular_user = User.objects.create_user(
            email="user@tourmate.test",
            first_name="Regular",
            last_name="User",
            admin_role=AdminRole.NONE,
        )
        self.regular_token = generate_access_token(self.regular_user)

        # Create Sub-Admin / Moderator
        self.sub_admin = User.objects.create_user(
            email="subadmin@tourmate.test",
            first_name="Sub",
            last_name="Admin",
            admin_role=AdminRole.SUB_ADMIN,
            is_staff=True,
        )
        self.sub_token = generate_access_token(self.sub_admin)

        # Create a sample Tour
        self.tour = Tour.objects.create(
            title="Bandarban Trekking 2026",
            description="Hill trek",
            budget_limit=Decimal("15000.00"),
            color_theme="#059669",
            created_by=self.regular_user,
        )
        self.member = TourMember.objects.create(
            tour=self.tour,
            user=self.regular_user,
            name="Regular",
            role=TourMember.Role.OWNER,
        )
        Deposit.objects.create(tour=self.tour, member=self.member, amount=Decimal("5000.00"))
        Expense.objects.create(
            tour=self.tour,
            purpose="Cottage rent",
            amount=Decimal("3000.00"),
            created_by=self.regular_user,
        )

    def test_auto_super_admin_backup(self):
        """Test that provision_google_user auto-grants SUPER_ADMIN to .env configured email."""
        with self.settings(SUPER_ADMIN_EMAILS=["owner@tourmate.test"]):
            payload = {
                "email": "OWNER@tourmate.test",
                "given_name": "Main",
                "family_name": "Owner",
            }
            user = provision_google_user(payload)
            self.assertEqual(user.admin_role, AdminRole.SUPER_ADMIN)
            self.assertTrue(user.is_staff)
            self.assertTrue(user.is_superuser)
            self.assertTrue(user.is_super_admin)

    def test_admin_access_control(self):
        """Test regular user receives 403 on admin endpoints, super admin receives 200."""
        # Regular user denied
        resp = self.client.get(
            "/api/v1/admin/me",
            HTTP_AUTHORIZATION=f"Bearer {self.regular_token}",
        )
        self.assertEqual(resp.status_code, 403)

        # Super admin allowed
        resp_admin = self.client.get(
            "/api/v1/admin/me",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp_admin.status_code, 200)
        data = resp_admin.json()
        self.assertEqual(data["admin_role"], "SUPER_ADMIN")
        self.assertTrue(data["can_manage_users"])
        self.assertTrue(data["can_manage_cms"])

    def test_metrics_overview(self):
        """Test live platform metrics calculation."""
        resp = self.client.get(
            "/api/v1/admin/metrics",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["users_total"], 3)
        self.assertGreaterEqual(data["tours_total"], 1)
        self.assertEqual(float(data["total_deposits_volume"]), 5000.0)
        self.assertEqual(float(data["total_expenses_volume"]), 3000.0)

    def test_user_role_management(self):
        """Test super admin promoting regular user to Sub-Admin, and preventing invalid demotions."""
        # Promote regular user
        resp = self.client.put(
            f"/api/v1/admin/users/{self.regular_user.id}/role",
            data={"admin_role": "SUB_ADMIN"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp.status_code, 200)
        self.regular_user.refresh_from_db()
        self.assertEqual(self.regular_user.admin_role, "SUB_ADMIN")
        self.assertTrue(self.regular_user.is_staff)

        # Sub-admin cannot change roles
        resp_forbidden = self.client.put(
            f"/api/v1/admin/users/{self.regular_user.id}/role",
            data={"admin_role": "SUPER_ADMIN"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.sub_token}",
        )
        self.assertEqual(resp_forbidden.status_code, 403)

    def test_tour_god_mode_crud(self):
        """Test God-mode listing, editing, and deleting tours."""
        # List tours
        resp = self.client.get(
            "/api/v1/admin/tours",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp.status_code, 200)
        tours = resp.json()
        self.assertEqual(len(tours), 1)
        self.assertEqual(float(tours[0]["fund_balance"]), 2000.0)

        # Edit tour
        edit_resp = self.client.put(
            f"/api/v1/admin/tours/{self.tour.id}",
            data={"title": "Bandarban Luxury Trek 2026", "color_theme": "#E11D48"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.tour.refresh_from_db()
        self.assertEqual(self.tour.title, "Bandarban Luxury Trek 2026")
        self.assertEqual(self.tour.color_theme, "#E11D48")

        # Delete tour
        del_resp = self.client.delete(
            f"/api/v1/admin/tours/{self.tour.id}",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(Tour.objects.filter(id=self.tour.id).exists())

    def test_site_config_and_scheduled_announcement(self):
        """Test No-Code Site Customizer and scheduled popup announcement."""
        # Update site config
        now = django_tz.now()
        payload = {
            "app_name": "TourMate Pro",
            "slogan_bn": "ট্যুর হোক সহজ, হিসাব নিখুঁত",
            "primary_color": "#4F46E5",
            "custom_themes": ["#2563EB", "#059669", "#E11D48", "#10B981"],
            "announcement_enabled": True,
            "announcement_id": "ann-2026-launch",
            "announcement_title_bn": "মেগা আপডেট!",
            "announcement_msg_bn": "নতুন অ্যাডমিন কনসোল লাইভ করা হয়েছে।",
            "announcement_start": (now - timedelta(hours=1)).isoformat(),
            "announcement_end": (now + timedelta(days=2)).isoformat(),
        }
        resp = self.client.put(
            "/api/v1/admin/config",
            data=payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp.status_code, 200)
        cfg = SiteConfig.get_solo()
        self.assertEqual(cfg.app_name, "TourMate Pro")
        self.assertEqual(cfg.primary_color, "#4F46E5")
        self.assertEqual(len(cfg.custom_themes), 4)

        # Public endpoint should show announcement when active
        pub_resp = self.client.get("/api/v1/public/config")
        self.assertEqual(pub_resp.status_code, 200)
        pub_data = pub_resp.json()
        self.assertIsNotNone(pub_data["announcement"])
        self.assertEqual(pub_data["announcement"]["id"], "ann-2026-launch")
        self.assertEqual(pub_data["announcement"]["title_bn"], "মেগা আপডেট!")

    def test_complaints_and_suggestions_desk_reply(self):
        """Test user submitting feedback, admin replying with timestamp, and user viewing reply."""
        # User submits feedback
        submit_resp = self.client.post(
            "/api/v1/feedback/",
            data={
                "feedback_type": "SUGGESTION",
                "message": "ট্যুরমেটে অফলাইন এক্সপোর্ট যোগ করলে খুব ভালো হতো।",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.regular_token}",
        )
        self.assertEqual(submit_resp.status_code, 201)
        feedback_id = submit_resp.json()["id"]

        # Admin replies to feedback
        reply_resp = self.client.post(
            f"/api/v1/admin/feedbacks/{feedback_id}/reply",
            data={
                "reply": "ধন্যবাদ! অফলাইন ফিচার ইতোমধ্যে প্রস্তুত এবং শীঘ্রই উন্মুক্ত করা হবে।",
                "status": "RESOLVED",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(reply_resp.status_code, 200)
        reply_data = reply_resp.json()
        self.assertEqual(reply_data["status"], "RESOLVED")
        self.assertIn("ধন্যবাদ!", reply_data["admin_reply"])
        self.assertIsNotNone(reply_data["replied_at"])

        # User views feedback feed, sees admin reply
        feed_resp = self.client.get(
            "/api/v1/feedback/",
            HTTP_AUTHORIZATION=f"Bearer {self.regular_token}",
        )
        self.assertEqual(feed_resp.status_code, 200)
        user_feed = feed_resp.json()
        item = next(f for f in user_feed if f["id"] == feedback_id)
        self.assertEqual(item["status"], "RESOLVED")
        self.assertIn("অফলাইন ফিচার", item["admin_reply"])
        self.assertIsNotNone(item["replied_at"])

    def test_super_admin_god_mode_tour_crud(self):
        """Test Super Admin has God-mode access across tours even without explicit membership."""
        # Super admin views tour dashboard (Read)
        resp = self.client.get(
            f"/api/v1/tours/{self.tour.id}/dashboard",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["tour"]["title"], "Bandarban Trekking 2026")

        # Super admin edits tour (Edit)
        edit_resp = self.client.put(
            f"/api/v1/tours/{self.tour.id}",
            data={"title": "Bandarban Trekking 2026 (Updated by Super Admin)"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.tour.refresh_from_db()
        self.assertEqual(self.tour.title, "Bandarban Trekking 2026 (Updated by Super Admin)")

        # Super admin deletes expense (Delete)
        exp = Expense.objects.filter(tour=self.tour).first()
        del_exp_resp = self.client.delete(
            f"/api/v1/tours/{self.tour.id}/expenses/{exp.id}",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(del_exp_resp.status_code, 200)
        self.assertFalse(Expense.objects.filter(id=exp.id).exists())

    def test_demo_user_locked_from_admin_and_feedback(self):
        """Test demo user Alex Rivers has zero admin rights and cannot submit feedback."""
        # Demo login
        demo_resp = self.client.post("/api/v1/auth/demo")
        self.assertEqual(demo_resp.status_code, 200)
        demo_data = demo_resp.json()
        demo_token = demo_data["access_token"]
        user_info = demo_data["user"]
        self.assertEqual(user_info["admin_role"], "NONE")
        self.assertFalse(user_info["is_staff"])
        self.assertFalse(user_info["is_superuser"])

        # Attempt to access admin console -> 403
        admin_resp = self.client.get(
            "/api/v1/admin/me",
            HTTP_AUTHORIZATION=f"Bearer {demo_token}",
        )
        self.assertEqual(admin_resp.status_code, 403)

        # Attempt to submit feedback -> 403
        fb_resp = self.client.post(
            "/api/v1/feedback/",
            data={"feedback_type": "COMPLAINT", "message": "Demo complaint attempt"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {demo_token}",
        )
        self.assertEqual(fb_resp.status_code, 403)

    def test_feedback_edit_and_delete_by_super_admin(self):
        """Test Super Admin editing and deleting complaints/suggestions."""
        fb = Feedback.objects.create(
            user=self.regular_user,
            user_name="Regular User",
            user_email="user@tourmate.test",
            feedback_type="COMPLAINT",
            message="Original complaint message",
        )

        # Super admin edits feedback
        update_resp = self.client.put(
            f"/api/v1/admin/feedbacks/{fb.id}",
            data={
                "message": "Edited complaint message by Super Admin",
                "status": "RESOLVED",
                "admin_reply": "Under review by team.",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(update_resp.status_code, 200)
        fb.refresh_from_db()
        self.assertEqual(fb.message, "Edited complaint message by Super Admin")
        self.assertEqual(fb.status, "RESOLVED")
        self.assertEqual(fb.admin_reply, "Under review by team.")

        # Super admin deletes feedback
        del_resp = self.client.delete(
            f"/api/v1/admin/feedbacks/{fb.id}",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(Feedback.objects.filter(id=fb.id).exists())

    def test_user_inactivity_tracking_and_filtering(self):
        """Test listing users with last_login and inactivity filters."""
        # Regular user has not logged in yet (never)
        resp_never = self.client.get(
            "/api/v1/admin/users?activity=never",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp_never.status_code, 200)
        emails = [u["email"] for u in resp_never.json()]
        self.assertIn("user@tourmate.test", emails)

        # Simulate last login on regular user
        self.regular_user.last_login = django_tz.now() - timedelta(days=15)
        self.regular_user.save(update_fields=["last_login"])

        resp_inactive_7d = self.client.get(
            "/api/v1/admin/users?activity=inactive_7d",
            HTTP_AUTHORIZATION=f"Bearer {self.super_token}",
        )
        self.assertEqual(resp_inactive_7d.status_code, 200)
        inactive_emails = [u["email"] for u in resp_inactive_7d.json()]
        self.assertIn("user@tourmate.test", inactive_emails)

