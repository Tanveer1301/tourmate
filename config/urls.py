from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path

from apps.api import api
from apps.web import views

urlpatterns = [
    # Seamlessly route /admin and /admin/ to TourMate Admin Console
    path("admin/", lambda req: redirect("/admin-console", permanent=False)),
    path("admin", lambda req: redirect("/admin-console", permanent=False)),
    path("django-admin/", admin.site.urls),
    # Primary API Gateway mounted at /api/v1/
    path("api/v1/", api.urls),
    # PWA Web App Manifest & Dynamic Icons (Chrome / Safari Add to Home Screen)
    path("manifest.json", views.manifest_view, name="manifest"),
    path("apple-touch-icon.png", views.apple_touch_icon_view, name="apple_touch_icon"),
    path("apple-touch-icon-precomposed.png", views.apple_touch_icon_view, name="apple_touch_icon_precomposed"),
    path("favicon.ico", views.favicon_view, name="favicon"),
    # Mobile-First Web Frontend Routes
    path("", views.index_view, name="index"),
    path("login", views.login_view, name="login"),
    path("login/", views.login_view, name="login_slash"),
    path("dashboard", views.dashboard_view, name="dashboard"),
    path("dashboard/", views.dashboard_view, name="dashboard_slash"),
    path("tours", views.dashboard_view, name="tours"),
    path("tours/", views.dashboard_view, name="tours_slash"),
    path("tours/<uuid:tour_id>", views.tour_detail_view, name="tour_detail"),
    path("tours/<uuid:tour_id>/", views.tour_detail_view, name="tour_detail_slash"),
    # TourMate Admin Console
    path("admin-console", views.admin_console_view, name="admin_console"),
    path("admin-console/", views.admin_console_view, name="admin_console_slash"),
    # Direct Google OAuth2 Redirect Flow
    path("auth/google/login", views.google_oauth_login, name="google_oauth_login"),
    path("auth/google/login/", views.google_oauth_login, name="google_oauth_login_slash"),
    path("auth/google/callback", views.google_oauth_callback, name="google_oauth_callback"),
    path("auth/google/callback/", views.google_oauth_callback, name="google_oauth_callback_slash"),
]
