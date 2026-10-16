import json
import logging
import os
import urllib.parse
import requests
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render

from apps.accounts.security import generate_access_token, provision_google_user

logger = logging.getLogger(__name__)


def _get_redirect_uri(request):
    """Dynamically determine the canonical OAuth callback URL."""
    custom_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    if custom_uri:
        return custom_uri.strip()
    scheme = "https" if (
        request.is_secure()
        or request.headers.get("x-forwarded-proto") == "https"
        or request.META.get("HTTP_X_FORWARDED_PROTO") == "https"
    ) else request.scheme
    host = request.get_host()
    # Strip standard default ports if present
    if host.endswith(":80"):
        host = host[:-3]
    elif host.endswith(":443"):
        host = host[:-4]
    return f"{scheme}://{host}/auth/google/callback"


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


def google_oauth_login(request):
    """Direct Google OAuth2 redirect flow (works 100% across all mobile browsers and webviews)."""
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    if not client_id:
        return HttpResponseBadRequest("GOOGLE_CLIENT_ID is not configured.")

    next_url = request.GET.get("next", "/tours")
    redirect_uri = _get_redirect_uri(request)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": next_url,
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return redirect(url)


def google_oauth_callback(request):
    """Handles Google OAuth2 callback, exchanges code for user profile, and sets JWT in browser."""
    code = request.GET.get("code")
    error = request.GET.get("error")
    next_url = request.GET.get("state", "/tours")
    if not next_url or not next_url.startswith("/"):
        next_url = "/tours"

    if error or not code:
        logger.warning("Google OAuth error: %s", error)
        return redirect(f"/login?error={urllib.parse.quote(error or 'No authorization code received')}")

    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", "")
    redirect_uri = _get_redirect_uri(request)

    try:
        # Exchange authorization code for tokens
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        if token_resp.status_code != 200:
            logger.error("Google token exchange failed: %s %s", token_resp.status_code, token_resp.text)
            return redirect("/login?error=token_exchange_failed")

        tokens = token_resp.json()
        access_token_google = tokens.get("access_token")

        # Fetch Google user profile
        userinfo_resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token_google}"},
            timeout=10,
        )
        if userinfo_resp.status_code != 200:
            logger.error("Google userinfo failed: %s %s", userinfo_resp.status_code, userinfo_resp.text)
            return redirect("/login?error=userinfo_failed")

        user_info = userinfo_resp.json()
        user = provision_google_user(user_info)
        jwt_token = generate_access_token(user)

        user_data = {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "avatar_url": user.avatar_url,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }

        payload_json = json.dumps({
            "token": jwt_token,
            "user": user_data,
            "next": next_url,
        })

        # Bridge HTML page that safely sets localStorage and redirects
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TourMate - প্রবেশ করা হচ্ছে...</title>
</head>
<body style="background:#0f172a;color:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">
    <div style="text-align:center;">
        <div style="width:48px;height:48px;border:4px solid rgba(59,130,246,0.2);border-top-color:#3b82f6;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px;"></div>
        <p style="font-size:15px;font-weight:600;margin:0 0 6px 0;">লগইন সফল হয়েছে!</p>
        <p style="font-size:12px;color:#94a3b8;margin:0;">ট্যুর ড্যাশবোর্ডে প্রবেশ করা হচ্ছে...</p>
    </div>
    <style>@keyframes spin {{ to {{ transform: rotate(360deg); }} }}</style>
    <script id="auth-data" type="application/json">{payload_json}</script>
    <script>
        try {{
            const raw = document.getElementById('auth-data').textContent;
            const data = JSON.parse(raw);
            if (data.token) {{
                localStorage.setItem('tourmate_token', data.token);
            }}
            if (data.user) {{
                localStorage.setItem('tourmate_user', JSON.stringify(data.user));
            }}
            window.location.replace(data.next || '/tours');
        }} catch(e) {{
            window.location.replace('/tours');
        }}
    </script>
</body>
</html>"""
        return HttpResponse(html)
    except Exception as err:
        logger.error("Google OAuth callback exception: %s", err, exc_info=True)
        return redirect("/login?error=auth_failed")
