# voip/backends/twiliobackend.py  — UPDATED with number pool rotation
"""
Twilio outbound-callback backend for django-crm.

WHAT CHANGED VS THE ORIGINAL
─────────────────────────────
1. Added select_caller_id() — area-code matching pool rotation.
2. make_query() now uses the pool to pick the best From number.
3. All pool configuration lives in the VOIP settings dict under OPTIONS.
4. No new global settings keys needed.

DOES ZADARMA SUPPORT POOLING?
──────────────────────────────
No. The ZadarmaAPI.make_query() signature passes `from_num` (the agent's
registered SIP/PBX extension number) directly to Zadarma's
/v1/request/callback/ API. Zadarma does have a "virtual number" concept but
it is configured on the Zadarma dashboard per-agent, not as a pool in the
application layer. The ZadarmaAPI class in django-crm has a single key+secret
pair and does not implement multi-number selection at all.

Twilio's architecture is different: you own multiple phone numbers and choose
which one appears as the caller ID on each call. This is where pool rotation
adds value.

HOW POOL ROTATION WORKS
────────────────────────
You buy several Twilio phone numbers covering different area codes.
When a call is placed:
  1. Extract the first 3 digits (area code) of the lead's number.
  2. Look for a Twilio number in the pool whose digits contain that area code.
  3. If found, use that number → lead sees a "local" number → answer rate ↑
  4. If no area-code match, fall back to a random pool number.

Example:
  Pool:    ["+14041112222", "+17701113333", "+16781114444"]  (Atlanta-area codes)
  Lead:    +14045559876  (404 area code)
  Chosen:  +14041112222  (404 match)

SETTINGS STRUCTURE
──────────────────
In voip/settings.py, add TWILIO_NUMBER_POOL to OPTIONS:

  {
    "BACKEND": "voip.backends.twiliobackend.TwilioAPI",
    "PROVIDER": "Twilio",
    "IP": "",
    "OPTIONS": {
        "key":              os.environ.get("TWILIO_ACCOUNT_SID", ""),
        "secret":           os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "twilio_number":    os.environ.get("TWILIO_NUMBER", ""),      # single-number fallback
        "number_pool":      os.environ.get("TWILIO_NUMBER_POOL", "").split(","),  # comma-sep list
        "twiml_url":        os.environ.get("TWILIO_TWIML_URL", ""),
        "status_url":       os.environ.get("TWILIO_STATUS_URL", ""),
        "webhook_secret":   os.environ.get("TWILIO_WEBHOOK_SECRET", ""),
    },
  }

Environment variable:
  TWILIO_NUMBER_POOL=+14041112222,+17701113333,+16781114444

Pool and single-number can coexist:
  - If number_pool is non-empty → pool selection is used.
  - If number_pool is empty or [""] → falls back to twilio_number.
"""

__version__ = "2.0.0"

import json
import logging
import random

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


class TwilioAPI:
    """
    Twilio outbound-callback backend.

    Interface contract (identical to ZadarmaAPI):
        __init__(key, secret, is_sandbox=False)
        make_query(from_num, to_num, sip=None) → JSON string
    """

    def __init__(self, key: str, secret: str, is_sandbox: bool = False):
        """
        :param key:     Twilio Account SID  (OPTIONS['key'])
        :param secret:  Twilio Auth Token   (OPTIONS['secret'])
        """
        self.account_sid = key
        self.auth_token = secret
        # is_sandbox kept for interface parity; Twilio has no sandbox mode via REST

    # ------------------------------------------------------------------
    # Pool selection
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_area_code(e164_number: str) -> str:
        """
        Extract 3-digit US area code from an E.164 number.
        +14045551234  →  '404'
        14045551234   →  '404'   (leading 1 stripped)
        """
        digits = ''.join(c for c in e164_number if c.isdigit())
        if digits.startswith('1') and len(digits) == 11:
            digits = digits[1:]   # strip US country code
        return digits[:3]

    @staticmethod
    def select_caller_id(destination_number: str, options: dict) -> str | None:
        """
        Choose a From number using area-code matching pool rotation.

        Priority:
          1. Pool number whose digits contain the destination area code
          2. Random pool number (no area match)
          3. options['twilio_number']  (single-number fallback)

        :param destination_number:  Lead's phone number (any format)
        :param options:             OPTIONS dict from settings.VOIP entry
        :returns:                   E.164 phone number string, or None if misconfigured
        """
        pool = [
            n.strip() for n in options.get('number_pool', [])
            if n and n.strip()
        ]

        if not pool:
            # Fall back to single twilio_number
            single = options.get('twilio_number', '').strip()
            if single:
                return single
            logger.error(
                "TwilioAPI: number_pool is empty and twilio_number is not set. "
                "Configure at least one of these in VOIP OPTIONS."
            )
            return None

        # Area-code matching
        area_code = TwilioAPI._extract_area_code(destination_number)
        if area_code:
            matched = [n for n in pool if area_code in n]
            if matched:
                chosen = random.choice(matched)
                logger.debug(
                    "TwilioAPI: area-code %s matched → selected %s from pool %s",
                    area_code, chosen, matched
                )
                return chosen

        # No area match — random selection
        chosen = random.choice(pool)
        logger.debug(
            "TwilioAPI: no area-code match for %s → random pool selection → %s",
            destination_number, chosen
        )
        return chosen

    # ------------------------------------------------------------------
    # Public interface — identical signature to ZadarmaAPI.make_query
    # ------------------------------------------------------------------

    def make_query(self, from_num: str, to_num: str, sip: str = None) -> str:
        """
        Initiate a Twilio outbound callback.

        Twilio calls from_num (the AGENT) first.
        When the agent answers, Twilio fetches the TwiML URL which dials to_num (the LEAD).

        :param from_num:  Agent's phone in E.164 (e.g. +14045550199)
        :param to_num:    Lead's phone in E.164 (e.g. +14045551234)
        :param sip:       Ignored — Zadarma-only concept, kept for interface parity
        :returns:         JSON string — {"status": "success", "call_sid": "CA..."}
                                     or {"status": "error", "message": "..."}
        """
        from django.conf import settings

        # Locate the Twilio backend OPTIONS block in settings.VOIP
        backend_cfg = next(
            (b for b in settings.VOIP if b.get("PROVIDER") == "Twilio"),
            None
        )
        if backend_cfg is None:
            return json.dumps({
                "status": "error",
                "message": "Twilio provider not found in settings.VOIP"
            })

        options = backend_cfg.get("OPTIONS", {})
        twiml_url = options.get("twiml_url", "")
        status_url = options.get("status_url", "")

        if not twiml_url:
            return json.dumps({
                "status": "error",
                "message": "twiml_url not configured in VOIP OPTIONS"
            })

        # Pool selection — choose the best caller ID
        caller_id = self.select_caller_id(to_num, options)
        if not caller_id:
            return json.dumps({
                "status": "error",
                "message": "No caller ID available. Set number_pool or twilio_number in OPTIONS."
            })

        # Pass the lead's number as a query param so twiml.py can bridge the call
        full_twiml_url = f"{twiml_url}?to={to_num}"

        url = f"{TWILIO_API_BASE}/Accounts/{self.account_sid}/Calls.json"
        payload = {
            "To":                  from_num,        # Agent — Twilio calls this FIRST
            "From":                caller_id,       # Pool-selected Twilio number
            "Url":                 full_twiml_url,
            "Method":              "GET",
            "StatusCallback":      status_url,
            "StatusCallbackMethod":"POST",
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
            logger.error("TwilioAPI: HTTP error calling Twilio REST API: %s", exc)
            return json.dumps({"status": "error", "message": str(exc)})

        if resp.status_code in (200, 201):
            body = resp.json()
            call_sid = body.get("sid", "")
            logger.info(
                "TwilioAPI: call initiated — SID %s | from=%s to=%s via pool=%s",
                call_sid, from_num, to_num, caller_id
            )
            return json.dumps({
                "status": "success",
                "call_sid": call_sid,
                "caller_id_used": caller_id,   # extra field for logging (get_callback ignores it)
            })
        else:
            try:
                err_body = resp.json()
                msg = err_body.get("message", resp.text)
            except Exception:
                msg = resp.text
            logger.error(
                "TwilioAPI: Twilio returned %s — %s | from=%s to=%s",
                resp.status_code, msg, from_num, to_num
            )
            return json.dumps({"status": "error", "message": msg})
