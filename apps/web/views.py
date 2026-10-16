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
<body style="background:#f8fafc;color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px;box-sizing:border-box;">
    <div style="text-align:center;background:#ffffff;border:1px solid #e2e8f0;border-radius:24px;padding:32px 24px;max-width:360px;width:100%;box-shadow:0 10px 25px -5px rgba(0,0,0,0.05);">
        <div style="width:48px;height:48px;border:4px solid #e0e7ff;border-top-color:#2563eb;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px;"></div>
        <p style="font-size:16px;font-weight:700;color:#0f172a;margin:0 0 6px 0;">লগইন সফল হয়েছে!</p>
        <p style="font-size:13px;color:#64748b;margin:0 0 16px 0;">ট্যুর ড্যাশবোর্ডে নিয়ে যাওয়া হচ্ছে...</p>
        <a id="direct-btn" href="{next_url or '/tours'}" style="display:inline-block;padding:8px 16px;background:#2563eb;color:#ffffff;text-decoration:none;border-radius:12px;font-size:12px;font-weight:600;opacity:0.9;">সরাসরি প্রবেশ করুন &rarr;</a>
    </div>
    <style>@keyframes spin {{ to {{ transform: rotate(360deg); }} }}</style>
    <script id="auth-data" type="application/json">{payload_json}</script>
    <script>
        (function() {{
            try {{
                const raw = document.getElementById('auth-data').textContent;
                const data = JSON.parse(raw);
                if (data.token) {{
                    try {{ localStorage.setItem('tourmate_token', data.token); }} catch(e) {{}}
                    document.cookie = 'tourmate_token=' + encodeURIComponent(data.token) + '; path=/; max-age=604800; SameSite=Lax';
                }}
                if (data.user) {{
                    try {{ localStorage.setItem('tourmate_user', JSON.stringify(data.user)); }} catch(e) {{}}
                    document.cookie = 'tourmate_user=' + encodeURIComponent(JSON.stringify(data.user)) + '; path=/; max-age=604800; SameSite=Lax';
                }}
                const target = data.next || '/tours';
                try {{
                    window.location.replace(target);
                }} catch(e) {{
                    window.location.href = target;
                }}
                setTimeout(function() {{
                    window.location.href = target;
                }}, 300);
            }} catch(e) {{
                window.location.href = '/tours';
            }}
        }})();
    </script>
</body>
</html>"""
        return HttpResponse(html)
    except Exception as err:
        logger.error("Google OAuth callback exception: %s", err, exc_info=True)
        return redirect("/login?error=auth_failed")
