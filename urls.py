"""
voip/urls.py
=============
Original Zadarma routes are preserved unchanged.
Two Twilio-specific routes are appended at the bottom.

Route summary
-------------
  /voip/get-callback/          ConnectionView   — agent clicks call icon in CRM
  /voip/zd/                    VoIPWebHook      — Zadarma PBX notification webhook
  /voip/twilio/twiml/          TwilioTwiML      — Twilio fetches TwiML when agent answers
  /voip/twilio/status/         TwilioWebHook    — Twilio call-status notifications

Register both Twilio URLs in your Twilio console / REST call:
  Url (TwiML):          https://<your-domain>/voip/twilio/twiml/
  StatusCallback:       https://<your-domain>/voip/twilio/status/
"""

from django.urls import path

# --- original views (unchanged) ---
from voip.views.callback import ConnectionView
from voip.views.voipwebhook import VoIPWebHook

# --- new Twilio views ---
from voip.views.twiml import TwilioTwiML
from voip.views.twiliowebhook import TwilioWebHook


urlpatterns = [
    # -----------------------------------------------------------------------
    # Original Zadarma routes — DO NOT modify
    # -----------------------------------------------------------------------
    path(
        "get-callback/",
        ConnectionView.as_view(),
        name="get_callback",
    ),
    path(
        "zd/",
        VoIPWebHook.as_view(),
        name="voip-zadarma-pbx-notification",
    ),

    # -----------------------------------------------------------------------
    # Twilio routes (new)
    # -----------------------------------------------------------------------

    # Twilio fetches this when the agent answers the callback.
    # Returns TwiML <Dial> to bridge agent to the lead's number.
    path(
        "twilio/twiml/",
        TwilioTwiML.as_view(),
        name="twilio-twiml",
    ),

    # Twilio posts call-status events here (initiated, ringing, answered,
    # completed, failed, etc.).  Mirrors Zadarma's NOTIFY_END / NOTIFY_OUT_END
    # handling in VoIPWebHook.
    path(
        "twilio/status/",
        TwilioWebHook.as_view(),
        name="twilio-status-webhook",
    ),
]
