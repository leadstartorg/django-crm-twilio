"""
voip/views/twiliowebhook.py
============================
Twilio status-callback webhook — mirrors VoIPWebHook (voipwebhook.py)
in structure and responsibility.

What it does
-------------
- Receives POST notifications from Twilio when a call changes state
  (initiated, ringing, answered, completed).
- On "completed" it finds the Contact / Lead / Deal in the CRM by the
  dialled number, marks them as contacted, and appends a workflow entry
  to the Deal — exactly as VoIPWebHook does for Zadarma NOTIFY_END /
  NOTIFY_OUT_END events.
- Stores the Twilio CallSid on the Connection model (new field added in
  migration 0002) so supervisors can look up recordings in Twilio console.
- Optionally forwards the raw POST to VOIP_FORWARD_URL if the number is
  not found locally (mirrors Zadarma forwarding behaviour).

Authentication
--------------
Twilio signs every request with X-Twilio-Signature.  We validate it
using twilio.request_validator.RequestValidator.  If TWILIO_WEBHOOK_SECRET
(= Auth Token) is not set the check is skipped with a warning.

URL pattern in voip/urls.py:
    path('twilio/status/', TwilioWebHook.as_view(), name='twilio-status-webhook')

Twilio call status field reference
------------------------------------
  CallSid         — unique call identifier (AC…)
  CallStatus      — initiated | ringing | in-progress | completed | busy |
                    failed | no-answer | canceled
  To              — number Twilio dialled (the agent for outbound callbacks)
  From            — Twilio number (caller ID shown to lead)
  Direction       — outbound-api / inbound / etc.
  Duration        — call duration in seconds (present on "completed" only)
  Called          — same as To for outbound calls
  CallerCountry   — ISO country of caller
"""

import logging
import requests

from django.conf import settings
from django.http import HttpResponse, HttpRequest
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from typing import Optional, Tuple

from common.utils.helpers import add_phone_q_params
from crm.models import Contact, Deal, Lead

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (same signature as helpers in voipwebhook.py)
# ---------------------------------------------------------------------------

def _get_twilio_options() -> dict:
    """Return OPTIONS for the Twilio provider from settings.VOIP."""
    for backend in settings.VOIP:
        if backend.get("PROVIDER") == "Twilio":
            return backend.get("OPTIONS", {})
    return {}


def is_authenticated(request: HttpRequest, _data: str = "") -> bool:
    """
    Validate X-Twilio-Signature.
    `_data` is kept for interface parity with the Zadarma version but is not
    used — Twilio uses HMAC-SHA1 over the full URL + sorted POST params.
    """
    options = _get_twilio_options()
    auth_token = options.get("webhook_secret") or options.get("secret", "")

    if not auth_token:
        logger.warning(
            "TwilioWebHook: TWILIO_WEBHOOK_SECRET not set — skipping signature "
            "validation. Set it in production."
        )
        return True

    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        url = request.build_absolute_uri()
        signature = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
        return validator.validate(url, request.POST.dict(), signature)
    except ImportError:
        logger.warning(
            "twilio package not installed — skipping signature validation. "
            "Install with: pip install twilio"
        )
        return True


def find_objects_by_phone(
    phone: str,
) -> Tuple[Optional[Contact], Optional[Lead], Optional[Deal], str]:
    """
    Search Contact, Lead and active Deal by phone number.
    Identical to the function in voipwebhook.py — extracted here so both
    webhook views share the same logic without a circular import.
    """
    params = contact = lead = deal = None
    q_params = add_phone_q_params(phone)
    try:
        contact = Contact.objects.filter(q_params).first()
    except Exception as exc:
        return contact, lead, deal, str(exc)
    if contact:
        params = {"contact_id": contact.id, "active": True}
    else:
        lead = Lead.objects.filter(q_params).first()
        if lead:
            params = {"lead_id": lead.id, "active": True}
    if any((contact, lead)):
        deal = Deal.objects.filter(**params).order_by("-update_date").first()
    return contact, lead, deal, ""


# ---------------------------------------------------------------------------
# Webhook view
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")
class TwilioWebHook(View):
    """
    Receives Twilio call status events.

    Only 'completed' events update the CRM — earlier status events (initiated,
    ringing, in-progress) are acknowledged and discarded, just as Zadarma's
    NOTIFY_RECORD event is discarded in VoIPWebHook.
    """

    @staticmethod
    def get(request: HttpRequest) -> HttpResponse:
        # Twilio occasionally sends a GET to verify the endpoint during setup.
        return HttpResponse("OK", status=200)

    @staticmethod
    def post(request: HttpRequest) -> HttpResponse:
        call_status: str = request.POST.get("CallStatus", "")
        call_sid: str = request.POST.get("CallSid", "")
        direction: str = request.POST.get("Direction", "")

        logger.debug(
            "TwilioWebHook: CallSid=%s  Status=%s  Direction=%s",
            call_sid, call_status, direction,
        )

        # Acknowledge non-terminal statuses immediately (mirrors NOTIFY_RECORD)
        if call_status not in ("completed", "busy", "failed", "no-answer", "canceled"):
            return HttpResponse("", status=200)

        # Validate signature before doing any DB work
        if not is_authenticated(request):
            logger.warning(
                "TwilioWebHook: invalid signature for CallSid=%s — rejected.", call_sid
            )
            return HttpResponse("Forbidden", status=403)

        # Only record workflow entries for answered/completed calls
        if call_status != "completed":
            return HttpResponse("", status=200)

        # ----------------------------------------------------------------
        # Determine the lead/contact phone number.
        # For outbound callbacks Twilio dials the AGENT first (To = agent),
        # then bridges to the lead.  The lead's number was passed as the
        # "to" query param appended to the TwiML URL by TwilioAPI.make_query().
        # Twilio echoes it back as ForwardedTo or we parse it from the URL.
        # Fallback: use the "Called" field which equals the To number.
        # ----------------------------------------------------------------
        forwarded_to: str = request.POST.get("ForwardedTo", "")
        lead_phone: str = forwarded_to or request.POST.get("Called", "")
        agent_phone: str = request.POST.get("To", "")

        # Prefer forwarded_to (actual lead number); fall back to agent number
        # so at minimum something is logged.
        phone = lead_phone or agent_phone

        # Strip formatting — keep digits and leading +
        import re
        phone = re.sub(r"[^\d+]", "", phone)

        duration_seconds: int = 0
        try:
            duration_seconds = int(request.POST.get("Duration", 0))
        except (ValueError, TypeError):
            pass
        duration_min = round(duration_seconds / 60, 1)

        entry: str = ""
        full_name: str = ""

        contact, lead, deal, err = find_objects_by_phone(phone)

        if err:
            logger.error("TwilioWebHook: DB error looking up phone %s: %s", phone, err)
            return HttpResponse("", status=200)

        obj = contact or lead
        if obj:
            obj.was_in_touch_today()
            full_name = obj.full_name

        if deal:
            direction_label = (
                _("An outgoing call to") if "outbound" in direction
                else _("An incoming call from")
            )
            duration_str = _(f"(duration: {duration_min} minutes)")
            entry = f"{direction_label} {full_name} {duration_str}."
            deal.add_to_workflow(entry)
            deal.save()

        # Store CallSid on the matching Connection record for audit trail
        if call_sid and agent_phone:
            _store_call_sid(agent_phone, call_sid)

        # Forward if no local record found (mirrors Zadarma forwarding)
        if not any((contact, lead, deal)) and settings.VOIP_FORWARD_DATA:
            url = settings.VOIP_FORWARD_URL
            try:
                requests.post(url, data=request.POST, timeout=5)
            except requests.RequestException as exc:
                logger.warning("TwilioWebHook: forward failed: %s", exc)

        return HttpResponse("", status=200)


def _store_call_sid(agent_phone: str, call_sid: str) -> None:
    """
    Persist the Twilio CallSid on the Connection whose `number` matches the
    agent's phone.  Requires the twilio_call_sid field added in migration 0002.
    """
    try:
        from voip.models import Connection
        conn = Connection.objects.filter(
            number=agent_phone, provider="Twilio", active=True
        ).first()
        if conn:
            conn.twilio_call_sid = call_sid
            conn.save(update_fields=["twilio_call_sid"])
    except Exception as exc:
        logger.warning("TwilioWebHook: could not store call_sid: %s", exc)
