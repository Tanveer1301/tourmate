from django.conf import settings
from django.shortcuts import redirect, render


def index_view(request):
    """Entry point redirecting to dashboard or login."""
    return redirect("/tours")


def login_view(request):
    """Renders the mobile login screen with Google OAuth and demo login."""
    context = {
        "google_client_id": getattr(settings, "GOOGLE_CLIENT_ID", ""),
    }
    return render(request, "login.html", context)


def dashboard_view(request):
    """Renders the mobile tours list and dashboard."""
    return render(request, "dashboard.html")


def tour_detail_view(request, tour_id):
    """Renders the mobile tour detail workspace (3 tabs, deposits, expenses, settlement)."""
    return render(request, "tour_detail.html", {"tour_id": str(tour_id)})
