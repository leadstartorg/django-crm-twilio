"""
voip/migrations/0002_connection_twilio_call_sid.py
===================================================
Adds the optional `twilio_call_sid` field to the Connection model.

Why
---
TwilioWebHook stores the Twilio CallSid (e.g. "CA1234…") on the Connection
record that initiated each call so that supervisors can look up the call
recording directly in the Twilio Console without leaving the CRM.

The field is nullable so that:
  - Existing Zadarma Connection rows are unaffected (value remains NULL).
  - A Connection row can be reset between calls without needing a delete.

Run with:
    python manage.py migrate voip
"""

import django.db.migrations.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # This migration depends on the initial one that created Connection.
        ("voip", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="connection",
            name="twilio_call_sid",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Twilio CallSid of the most recent call made through this "
                    "connection.  Populated automatically by TwilioWebHook.  "
                    "Use it to look up recordings in the Twilio Console."
                ),
                max_length=64,
                verbose_name="Twilio Call SID",
            ),
        ),
    ]
