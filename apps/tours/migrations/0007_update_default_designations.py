from django.db import migrations


def update_designations(apps, schema_editor):
    SiteConfig = apps.get_model('tours', 'SiteConfig')
    default_designations = [
        "Chief Organizer",
        "Assistant Organizer",
        "Treasurer",
        "Planner",
        "Head of Catering",
        "Chief Visual Officer",
        "Navigation Specialist",
        "Silent Member",
        "The Sponsor",
        "Guest",
        "Chief Complain",
        "Low Battery",
        "Sound Engineer",
        "Always Late",
        "Sleeping",
    ]
    old_bengali = [
        "ক্যাশিয়ার / হিসাবরক্ষক",
        "ট্যুর লিডার",
        "ট্যুর ম্যানেজার",
        "ভোজনরসিক / খাদক",
        "অফিসিয়াল ফটোগ্রাফার",
        "ন্যাভিগেটর / দিকনির্দেশক",
        "ডিজে / এন্টারটেইনার",
        "দোকানদার পার্টনার",
    ]
    for cfg in SiteConfig.objects.all():
        if cfg.custom_designations == old_bengali or not cfg.custom_designations:
            cfg.custom_designations = default_designations
            cfg.save(update_fields=['custom_designations'])


class Migration(migrations.Migration):

    dependencies = [
        ('tours', '0006_siteconfig_feedback_admin_reply_feedback_replied_at_and_more'),
    ]

    operations = [
        migrations.RunPython(update_designations, migrations.RunPython.noop),
    ]
