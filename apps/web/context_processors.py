from apps.tours.models import SiteConfig


def site_branding(request):
    """
    Context processor providing live site branding, PWA home screen icon,
    and app title to all rendered templates.
    """
    try:
        cfg = SiteConfig.get_solo()
        logo_url = cfg.app_logo_url.strip() if (cfg.app_logo_url and cfg.app_logo_url.strip()) else "/static/icons/icon-192.png"
        return {
            "site_config": cfg,
            "app_logo_url": logo_url,
            "app_name": cfg.app_name or "TourMate",
        }
    except Exception:
        return {
            "site_config": None,
            "app_logo_url": "/static/icons/icon-192.png",
            "app_name": "TourMate",
        }
