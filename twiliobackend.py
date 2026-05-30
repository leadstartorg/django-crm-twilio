# -*- coding: utf-8 -*-
"""
TwilioAPI backend for django-crm VoIP integration.
Mirrors the ZadarmaAPI interface exactly so ConnectionView.get_callback()
works without modification — it calls backend_cls(key=..., secret=...)
and then backend.make_query(from_num, to_num).

Twilio mapping
--------------
  key    -> Twilio Account SID   (TWILIO_ACCOUNT_SID in settings)
  secret -> Twilio Auth Token    (TWILIO_AUTH_TOKEN  in settings)

Callback flow (mirrors Zadarma /v1/request/callback/)
------------------------------------------------------
1. CRM agent clicks the phone-icon next to a lead.
2. ConnectionView calls make_query(agent_number, lead_number).
3. We POST to Twilio REST API to create an outbound call TO the agent first.
4. When the agent answers Twilio fetches the TwiML at TWILIO_TWIML_URL,
   which dials the lead (see twiml.py).
5. Twilio posts status events to TWILIO_STATUS_URL (see twiliowebhook.py).

Return value
------------
Returns a JSON string {"status": "success"|"error", "message": "..."}
so that get_callback() in callback.py can parse it exactly as it does
for Zadarma without any modification.
"""
__version__ = "1.0.0"

import json
import requests
from requests.auth import HTTPBasicAuth


class TwilioAPI:
    """Twilio outbound-callback backend."""

    TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"

    def __init__(self, key: str, secret: str, is_sandbox: bool = False):
        """
        :param key:        Twilio Account SID
        :param secret:     Twilio Auth Token
        :param is_sandbox: Not used by Twilio; kept for interface parity.
        """
        self.account_sid = key
        self.auth_token = secret
        # twiml_url and status_url are injected from settings at call time
        # via OPTIONS; we read them lazily inside make_query.

    # ------------------------------------------------------------------
    # Public API — same signature as ZadarmaAPI.make_query
    # ------------------------------------------------------------------

    def make_query(self, from_num: str, to_num: str, sip: str = None) -> str:
        """
        Initiate a Twilio outbound callback.

        :param from_num:  Agent's phone number (E.164, e.g. +14045550100).
                          Twilio calls this number first.
        :param to_num:    Lead/contact phone number (E.164).
                          TwiML dials this number once the agent answers.
        :param sip:       Ignored (Zadarma-only concept); kept for parity.
        :return:          JSON string {"status": "success"|"error", "message": "..."}
        """
        from django.conf import settings

        # Pull Twilio-specific settings from the backend OPTIONS block
        voip_backends = settings.VOIP
        backend_cfg = next(
            (b for b in voip_backends if b["PROVIDER"] == "Twilio"), None
        )
        if backend_cfg is None:
            return json.dumps(
                {"status": "error", "message": "Twilio provider not found in settings.VOIP"}
            )

        options = backend_cfg.get("OPTIONS", {})
        twiml_url = options.get("twiml_url", "")
        status_url = options.get("status_url", "")
        twilio_number = options.get("twilio_number", from_num)

        if not twiml_url:
            return json.dumps(
                {"status": "error", "message": "TWILIO_TWIML_URL not configured in OPTIONS."}
            )

        url = f"{self.TWILIO_API_BASE}/Accounts/{self.account_sid}/Calls.json"

        # Twilio calls `from_num` (agent) first; TwiML then bridges to `to_num`.
        # We pass `to_num` as a URL param so twiml.py can read it from the
        # GET query string without storing state server-side.
        full_twiml_url = f"{twiml_url}?to={to_num}"

        payload = {
            "To": from_num,           # agent's phone — Twilio rings this first
            "From": twilio_number,    # your Twilio number (must be verified)
            "Url": full_twiml_url,    # TwiML fetched when agent answers
            "Method": "GET",
            "StatusCallback": status_url,
            "StatusCallbackMethod": "POST",
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
        }

        try:
            resp = requests.post(
                url,
                data=payload,
                auth=HTTPBasicAuth(self.account_sid, self.auth_token),
                timeout=10,
            )
        except requests.RequestException as exc:
            return json.dumps({"status": "error", "message": str(exc)})

        if resp.status_code in (200, 201):
            call_sid = resp.json().get("sid", "")
            return json.dumps({"status": "success", "call_sid": call_sid})
        else:
            try:
                err = resp.json()
                msg = err.get("message", resp.text)
            except Exception:
                msg = resp.text
            return json.dumps({"status": "error", "message": msg})
