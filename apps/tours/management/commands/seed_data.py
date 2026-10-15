from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from apps.accounts.security import generate_access_token
from apps.tours.models import Deposit, Expense, ExpenseComment, Tour, TourMember
from apps.tours.services.settlement import SettlementService

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds database with realistic TourMate group trip data and outputs demo JWT token."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding TourMate demo dataset..."))

        # 1. Create or get users
        alex, _ = User.objects.get_or_create(
            email="alex@tourmate.test",
            defaults={"first_name": "Alex", "last_name": "Rivers", "is_staff": True, "is_superuser": True},
        )
        alex.set_password("tourmate123")
        alex.save()

        sam, _ = User.objects.get_or_create(
            email="sam@tourmate.test",
            defaults={"first_name": "Sam", "last_name": "Chen"},
        )
        maya, _ = User.objects.get_or_create(
            email="maya@tourmate.test",
            defaults={"first_name": "Maya", "last_name": "Patel"},
        )

        token = generate_access_token(alex)

        # 2. Create Tour
        tour, created = Tour.objects.get_or_create(
            title="Sajek Valley Expedition 2026",
            defaults={
                "description": "4-day mountain getaway with cottage stays, trekking, and off-road 4x4 rides.",
                "color_theme": "#2563EB",
                "budget_limit": Decimal("1200.00"),
                "created_by": alex,
            },
        )

        if not created:
            self.stdout.write(self.style.SUCCESS(f"Tour already exists (ID: {tour.id})"))
        else:
            # 3. Create Members
            m_alex = TourMember.objects.create(
                tour=tour, user=alex, name="Alex Rivers", email=alex.email, role=TourMember.Role.OWNER
            )
            m_sam = TourMember.objects.create(
                tour=tour, user=sam, name="Sam Chen", email=sam.email, role=TourMember.Role.EDITOR
            )
            m_maya = TourMember.objects.create(
                tour=tour, user=maya, name="Maya Patel", email=maya.email, role=TourMember.Role.VIEWER
            )

            # 4. Deposits
            Deposit.objects.create(tour=tour, member=m_alex, amount=Decimal("400.00"), note="Initial bank transfer")
            Deposit.objects.create(tour=tour, member=m_sam, amount=Decimal("350.00"), note="Mobile wallet payment")
            Deposit.objects.create(tour=tour, member=m_maya, amount=Decimal("250.00"), note="Cash deposit to manager")

            # 5. Expenses
            exp1 = Expense.objects.create(
                tour=tour,
                purpose="Resort Cottage Booking",
                amount=Decimal("450.00"),
                paid_by=None,  # Common pool
                created_by=alex,
            )
            exp1.tagged_members.set([m_alex, m_sam, m_maya])

            exp2 = Expense.objects.create(
                tour=tour,
                purpose="Off-road 4x4 Chander Gari",
                amount=Decimal("180.00"),
                paid_by=None,  # Common pool
                created_by=alex,
            )
            exp2.tagged_members.set([m_alex, m_sam, m_maya])

            exp3 = Expense.objects.create(
                tour=tour,
                purpose="Hilltop Tribal BBQ Dinner",
                amount=Decimal("120.00"),
                paid_by=m_alex,  # Out-of-pocket by Alex
                created_by=alex,
            )
            exp3.tagged_members.set([m_alex, m_sam, m_maya])

            exp4 = Expense.objects.create(
                tour=tour,
                purpose="Kayaking & Gear Rental",
                amount=Decimal("60.00"),
                paid_by=m_sam,  # Out-of-pocket by Sam
                created_by=sam,
            )
            exp4.tagged_members.set([m_alex, m_sam])  # Selective split: Alex & Sam only

            ExpenseComment.objects.create(
                expense=exp1,
                author=alex,
                comment="Deposit confirmed with resort manager. Balcony view booked!",
            )
            ExpenseComment.objects.create(
                expense=exp3,
                author=sam,
                comment="The tribal barbecue was incredible. Thanks Alex for covering up front!",
            )

            SettlementService.record_activity(
                tour.id, alex, "TOUR_INITIALIZED", {"title": tour.title, "budget": "1200.00"}
            )

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("Demo Dataset Ready!"))
        self.stdout.write(self.style.SUCCESS(f"Tour ID: {tour.id}"))
        self.stdout.write(self.style.SUCCESS(f"Admin / Owner Email: alex@tourmate.test (password: tourmate123)"))
        self.stdout.write(self.style.SUCCESS(f"Bearer JWT Token:\n{token}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
