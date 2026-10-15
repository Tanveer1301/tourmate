import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_tour_invitation_email(tour, member, inviter=None, request=None) -> bool:
    """
    Sends an invitation email to the member if they have an email address.
    Uses settings.EMAIL_BACKEND (SMTP or Console).
    Fails silently so that member addition is never blocked if email fails.
    """
    if not member.email:
        return False

    if not getattr(settings, "ENABLE_AUTO_EMAIL_INVITATION", False):
        logger.info("Auto-email invitation is currently paused (ENABLE_AUTO_EMAIL_INVITATION=False).")
        return False

    try:
        if request:
            scheme = request.scheme
            host = request.get_host()
            invite_url = f"{scheme}://{host}/tours/{tour.id}"
        else:
            invite_url = f"http://127.0.0.1:8008/tours/{tour.id}"

        inviter_name = "আপনার বন্ধু"
        if inviter:
            inviter_name = getattr(inviter, "first_name", None) or getattr(inviter, "full_name", None) or getattr(inviter, "email", "আপনার বন্ধু")

        role_text = "ভিউয়ার (Viewer - View only)" if member.role == "VIEWER" else "এডিটর (Editor - খরচ ও হিসাব ব্যবস্থাপনা)"

        subject = f"TourMate: {inviter_name} আপনাকে '{tour.title}' ট্যুরে যুক্ত করেছেন"

        plain_message = (
            f"হ্যালো {member.name},\n\n"
            f"{inviter_name} আপনাকে TourMate-এ '{tour.title}' ট্যুরের হিসাব গ্রুপে আমন্ত্রণ জানিয়েছেন।\n"
            f"আপনার অ্যাক্সেস রোল: {role_text}\n\n"
            f"ট্যুরে যুক্ত হয়ে হিসাব ও বিবরণ দেখতে নিচের লিংকে প্রবেশ করুন:\n"
            f"{invite_url}\n\n"
            f"TourMate 2026 • Travel with Peace of Mind"
        )

        designation_row = ""
        if getattr(member, "designation", None):
            designation_row = f'<tr><td style="color: #64748b; padding: 6px 0;">পদবি:</td><td style="font-weight: 600; color: #475569; text-align: right; padding: 6px 0;">{member.designation}</td></tr>'

        html_message = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; padding: 24px 12px; margin: 0;">
    <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 24px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.04);">
        <div style="background: linear-gradient(135deg, #2563eb, #4f46e5); padding: 32px 24px; text-align: center; color: #ffffff;">
            <div style="display: inline-block; width: 48px; height: 48px; background: rgba(255,255,255,0.2); border-radius: 16px; margin-bottom: 12px; line-height: 48px; font-size: 24px;">✈️</div>
            <h1 style="margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">TourMate</h1>
            <p style="margin: 6px 0 0 0; font-size: 13px; opacity: 0.9;">ট্যুর ইনভাইটেশন ও হিসাব ব্যবস্থাপনা</p>
        </div>
        <div style="padding: 28px 24px;">
            <p style="margin: 0 0 16px 0; font-size: 15px; color: #1e293b; line-height: 1.6;">
                হ্যালো <strong>{member.name}</strong>,
            </p>
            <p style="margin: 0 0 20px 0; font-size: 14px; color: #475569; line-height: 1.6;">
                <strong>{inviter_name}</strong> আপনাকে <strong>'{tour.title}'</strong> ট্যুরের গ্রুপে যুক্ত করেছেন।
            </p>
            <div style="background: #f1f5f9; border-radius: 16px; padding: 16px; margin-bottom: 24px;">
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <tr>
                        <td style="color: #64748b; padding: 6px 0;">ট্যুর নাম:</td>
                        <td style="font-weight: 700; color: #0f172a; text-align: right; padding: 6px 0;">{tour.title}</td>
                    </tr>
                    <tr>
                        <td style="color: #64748b; padding: 6px 0;">আপনার রোল:</td>
                        <td style="font-weight: 700; color: #2563eb; text-align: right; padding: 6px 0;">{member.role}</td>
                    </tr>
                    {designation_row}
                </table>
            </div>
            <div style="text-align: center; margin: 32px 0 16px 0;">
                <a href="{invite_url}" style="display: inline-block; background: #2563eb; color: #ffffff; padding: 14px 32px; border-radius: 16px; font-weight: 700; font-size: 14px; text-decoration: none; box-shadow: 0 4px 12px rgba(37,99,235,0.25);">
                    ট্যুরে প্রবেশ করুন (View Tour) →
                </a>
            </div>
            <p style="margin: 16px 0 0 0; font-size: 12px; color: #94a3b8; text-align: center; line-height: 1.5;">
                লগইন পেজে "Sign in with Google" করলেই স্বয়ংক্রিয়ভাবে এই ট্যুরের ড্যাশবোর্ডে প্রবেশ করতে পারবেন।
            </p>
        </div>
        <div style="background: #f8fafc; padding: 16px 24px; text-align: center; border-top: 1px solid #e2e8f0;">
            <p style="margin: 0; font-size: 11px; color: #94a3b8;">TourMate 2026 • Travel with Peace of Mind</p>
        </div>
    </div>
</body>
</html>
        """.strip()

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[member.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info("Tour invitation email dispatched to %s for tour %s", member.email, tour.id)
        return True
    except Exception as err:
        logger.warning("Failed to dispatch tour invitation email to %s: %s", member.email, err)
        return False
