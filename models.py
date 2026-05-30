"""
voip/models.py
===============
Original Connection model with one new field: `twilio_call_sid`.

Changes from the original
--------------------------
- Added `twilio_call_sid` CharField (blank=True, default="") so that
  TwilioWebHook can persist the Twilio CallSid after each call.
  The field is blank/default-empty so it is invisible to Zadarma
  connections and requires no data migration.

Everything else is untouched — field order, choices, ForeignKey,
related_name pattern all match the original exactly.
"""

from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class Connection(models.Model):

    TYPE_CHOICES = [
        ("pbx", _("PBX extension")),
        ("sip", _("SIP connection")),
        ("voip", _("Virtual phone number")),
    ]

    # Build provider choices dynamically from settings.VOIP — same as original.
    PROVIDER_CHOICES = (
        (backend["PROVIDER"], backend["PROVIDER"])
        for backend in settings.VOIP
    )

    type = models.CharField(
        max_length=4,
        default="pbx",
        blank=False,
        choices=TYPE_CHOICES,
        verbose_name=_("Type"),
    )
    active = models.BooleanField(
        default=False,
        verbose_name=_("Active"),
    )
    number = models.CharField(
        max_length=30,
        null=False,
        blank=False,
        verbose_name=_("Number"),
    )
    callerid = models.CharField(
        max_length=30,
        null=False,
        blank=False,
        verbose_name=_("Caller ID"),
        help_text=_(
            "Specify the number to be displayed as "
            "your phone number when you call"
        ),
    )
    provider = models.CharField(
        max_length=100,
        null=False,
        blank=False,
        choices=PROVIDER_CHOICES,
        verbose_name=_("Provider"),
        help_text=_("Specify VoIP service provider"),
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        verbose_name=_("Owner"),
        related_name="%(app_label)s_%(class)s_owner_related",
    )

    # -----------------------------------------------------------------------
    # NEW FIELD — Twilio only
    # Zadarma connections leave this blank; Twilio connections get it
    # populated by TwilioWebHook._store_call_sid() after each completed call.
    # -----------------------------------------------------------------------
    twilio_call_sid = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name=_("Twilio Call SID"),
        help_text=_(
            "Twilio CallSid of the most recent call made through this "
            "connection.  Populated automatically by TwilioWebHook.  "
            "Use it to look up recordings in the Twilio Console."
        ),
    )
