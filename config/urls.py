from django.contrib import admin
from django.urls import path

from apps.api import api
from apps.web import views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Primary API Gateway mounted at /api/v1/
    path("api/v1/", api.urls),
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
]
