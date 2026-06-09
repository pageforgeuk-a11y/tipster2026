"""Create the 'Organiser' group used to gate the Manage area."""

from django.db import migrations


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Organiser")


def delete_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="Organiser").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("competition", "0004_questiontemplate"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group),
    ]
