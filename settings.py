"""
voip/settings.py — Twilio-aware version
========================================
Drop this file in place of the original  voip/settings.py.

WHAT CHANGED VS THE ORIGINAL
------------------------------
1. Added the Twilio backend dict to the VOIP list alongside Zadarma.
2. Every Twilio credential is pulled from os.environ so secrets are
   never committed to version control.  Set the env-vars in your
   server environment, .env file (loaded via python-decouple / django-environ),
   or Heroku/Railway config.
3. Original Zadarma block is left intact — both providers coexist.

Required environment variables
--------------------------------
  TWILIO_ACCOUNT_SID   — starts with "AC…"
  TWILIO_AUTH_TOKEN    — 32-char hex string
  TWILIO_NUMBER        — E.164 Twilio phone number, e.g. +14045550100
  TWILIO_TWIML_URL     — public URL of your twiml/ endpoint
                          e.g. https://crm.example.com/voip/twilio/twiml/
  TWILIO_STATUS_URL    — public URL of your status webhook
                          e.g. https://crm.example.com/voip/twilio/status/

Optional
--------
  TWILIO_WEBHOOK_SECRET — if you set this, TwilioWebHook will verify
                           X-Twilio-Signature on every inbound POST.
                           Leave empty to skip verification (dev only).
"""

import os

# ---------------------------------------------------------------------------
# Zadarma (original — unchanged)
# ---------------------------------------------------------------------------
SECRET_ZADARMA_KEY = os.environ.get("SECRET_ZADARMA_KEY", "123")
SECRET_ZADARMA = os.environ.get("SECRET_ZADARMA", "secret")

# ---------------------------------------------------------------------------
# Twilio credentials (from environment — never hardcode)
# ---------------------------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_NUMBER = os.environ.get("TWILIO_NUMBER", "")   # E.164 Twilio number
TWILIO_TWIML_URL = os.environ.get("TWILIO_TWIML_URL", "")
TWILIO_STATUS_URL = os.environ.get("TWILIO_STATUS_URL", "")
TWILIO_WEBHOOK_SECRET = os.environ.get("TWILIO_WEBHOOK_SECRET", "")

# ---------------------------------------------------------------------------
# VOIP backend list
# Both entries can coexist.  The Connection.provider field (set per user in
# Django Admin) selects which backend is used for each callback request.
# ---------------------------------------------------------------------------
VOIP = [
    # ---- Zadarma (original) ------------------------------------------------
    {
        "BACKEND": "voip.backends.zadarmabackend.ZadarmaAPI",
        "PROVIDER": "Zadarma",
        "IP": "185.45.152.42",          # Zadarma webhook source IP for auth
        "OPTIONS": {
            "key": SECRET_ZADARMA_KEY,
            "secret": SECRET_ZADARMA,
        },
    },

    # ---- Twilio (new) -------------------------------------------------------
    {
        "BACKEND": "voip.backends.twiliobackend.TwilioAPI",
        "PROVIDER": "Twilio",
        # Twilio webhook requests come from many IPs (they publish a CIDR list).
        # We authenticate via X-Twilio-Signature instead of IP.
        # Set "IP" to "" to disable IP-based auth for this provider.
        "IP": "",
        "OPTIONS": {
            # key / secret map to Account SID / Auth Token (see twiliobackend.py)
            "key": TWILIO_ACCOUNT_SID,
            "secret": TWILIO_AUTH_TOKEN,
            # Twilio-specific options read by TwilioAPI.make_query()
            "twilio_number": TWILIO_NUMBER,
            "twiml_url": TWILIO_TWIML_URL,
            "status_url": TWILIO_STATUS_URL,
            # Also consumed by TwilioWebHook for signature verification
            "webhook_secret": TWILIO_WEBHOOK_SECRET,
        },
    },
]

# ---------------------------------------------------------------------------
# Forward settings (original — unchanged)
# ---------------------------------------------------------------------------
VOIP_FORWARD_DATA = False
VOIP_FORWARDING_IP = ""
VOIP_FORWARD_URL = "Url to forward"
