from decimal import Decimal
from django.test import TestCase

from apps.accounts.models import User
from apps.tours.models import Deposit, Expense, Tour, TourMember
from apps.tours.services.settlement import SettlementService, round_currency


class SettlementServiceTestCase(TestCase):
    def setUp(self):
        # 1. Setup User and Tour
        self.creator = User.objects.create_user(email="creator@tourmate.test")
        self.user_a = User.objects.create_user(email="alice@tourmate.test")
        self.user_b = User.objects.create_user(email="bob@tourmate.test")
        self.user_c = User.objects.create_user(email="charlie@tourmate.test")

        self.tour = Tour.objects.create(
            title="Himchori Beach Retreat 2026",
            budget_limit=Decimal("500.00"),
            created_by=self.creator,
        )

        # 2. Setup Tour Members
        self.member_a = TourMember.objects.create(
            tour=self.tour,
            user=self.user_a,
            name="Alice",
            email=self.user_a.email,
            role=TourMember.Role.OWNER,
        )
        self.member_b = TourMember.objects.create(
            tour=self.tour,
            user=self.user_b,
            name="Bob",
            email=self.user_b.email,
            role=TourMember.Role.EDITOR,
        )
        self.member_c = TourMember.objects.create(
            tour=self.tour,
            user=self.user_c,
            name="Charlie",
            email=self.user_c.email,
            role=TourMember.Role.VIEWER,
        )

    def test_tour_summary_and_budget_progress(self):
        # Alice deposits 100.00, Bob deposits 150.00
        Deposit.objects.create(tour=self.tour, member=self.member_a, amount=Decimal("100.00"))
        Deposit.objects.create(tour=self.tour, member=self.member_b, amount=Decimal("150.00"))

        # Expense: 125.00 paid from common fund
        Expense.objects.create(
            tour=self.tour,
            purpose="Resort booking",
            amount=Decimal("125.00"),
            paid_by=None,
            created_by=self.creator,
        )

        summary = SettlementService.get_tour_summary(self.tour.id)
        self.assertEqual(summary["total_credit"], Decimal("250.00"))
        self.assertEqual(summary["total_debit"], Decimal("125.00"))
        self.assertEqual(summary["remaining_balance"], Decimal("125.00"))
        # Budget progress = 125.00 / 500.00 = 25.00%
        self.assertEqual(summary["budget_progress"], Decimal("25.00"))

    def test_settlement_selective_tagging_and_out_of_pocket(self):
        """
        Scenario:
        - Common pool deposits:
          - Alice: 100.00
          - Bob: 100.00
          - Charlie: 50.00
          Total credit = 250.00

        - Expense 1: 90.00 paid from Common Fund (paid_by=None), tagged_members empty -> split among all 3 (30.00 each)
        - Expense 2: 40.00 paid out-of-pocket by Alice (paid_by=Alice), tagged only Bob and Charlie -> 20.00 each
        """
        Deposit.objects.create(tour=self.tour, member=self.member_a, amount=Decimal("100.00"))
        Deposit.objects.create(tour=self.tour, member=self.member_b, amount=Decimal("100.00"))
        Deposit.objects.create(tour=self.tour, member=self.member_c, amount=Decimal("50.00"))

        # Expense 1: Common fund -> 90 / 3 = 30 each
        exp1 = Expense.objects.create(
            tour=self.tour,
            purpose="Shared transport van",
            amount=Decimal("90.00"),
            paid_by=None,
            created_by=self.creator,
        )

        # Expense 2: Alice paid 40 out of pocket for Bob and Charlie's boat ride -> 20 each for Bob & Charlie
        exp2 = Expense.objects.create(
            tour=self.tour,
            purpose="Boat ride excursion",
            amount=Decimal("40.00"),
            paid_by=self.member_a,
            created_by=self.creator,
            split_all=False,
        )
        exp2.tagged_members.set([self.member_b, self.member_c])


        settlement = SettlementService.get_member_settlements(self.tour.id)
        member_results = {m["member_id"]: m for m in settlement["members"]}

        # Alice:
        # deposited = 100.00
        # out_of_pocket = 40.00
        # allocated = 30.00 (from exp1)
        # net_balance = (100 + 40) - 30 = +110.00 (REFUNDABLE)
        alice_res = member_results[self.member_a.id]
        self.assertEqual(alice_res["total_deposited"], Decimal("100.00"))
        self.assertEqual(alice_res["out_of_pocket_paid"], Decimal("40.00"))
        self.assertEqual(alice_res["allocated_expense"], Decimal("30.00"))
        self.assertEqual(alice_res["net_balance"], Decimal("110.00"))
        self.assertEqual(alice_res["status"], "REFUNDABLE")

        # Bob:
        # deposited = 100.00
        # out_of_pocket = 0.00
        # allocated = 30.00 (exp1) + 20.00 (exp2) = 50.00
        # net_balance = 100 - 50 = +50.00 (REFUNDABLE)
        bob_res = member_results[self.member_b.id]
        self.assertEqual(bob_res["total_deposited"], Decimal("100.00"))
        self.assertEqual(bob_res["out_of_pocket_paid"], Decimal("0.00"))
        self.assertEqual(bob_res["allocated_expense"], Decimal("50.00"))
        self.assertEqual(bob_res["net_balance"], Decimal("50.00"))
        self.assertEqual(bob_res["status"], "REFUNDABLE")

        # Charlie:
        # deposited = 50.00
        # out_of_pocket = 0.00
        # allocated = 30.00 (exp1) + 20.00 (exp2) = 50.00
        # net_balance = 50 - 50 = 0.00 (SETTLED)
        charlie_res = member_results[self.member_c.id]
        self.assertEqual(charlie_res["total_deposited"], Decimal("50.00"))
        self.assertEqual(charlie_res["out_of_pocket_paid"], Decimal("0.00"))
        self.assertEqual(charlie_res["allocated_expense"], Decimal("50.00"))
        self.assertEqual(charlie_res["net_balance"], Decimal("0.00"))
        self.assertEqual(charlie_res["status"], "SETTLED")
