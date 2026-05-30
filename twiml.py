"""
voip/views/twiml.py
====================
TwiML endpoint — fetched by Twilio when the agent picks up the callback.

Flow
----
  1. Agent clicks the phone icon in CRM → ConnectionView → TwilioAPI.make_query()
  2. Twilio dials the AGENT's number (from_num / "To" in the REST call).
  3. Agent answers. Twilio fetches THIS URL (passed as the call's "Url" param).
  4. This view returns a <Response><Dial> that bridges the agent to the LEAD.

URL pattern added in voip/urls.py:
    path('twilio/twiml/', TwilioTwiML.as_view(), name='twilio-twiml')

The lead's number is passed as GET param ?to=<e164_number> — set by
TwilioAPI.make_query() when it appends it to the twiml_url.

Security
--------
Twilio signs every request with an X-Twilio-Signature header.
We validate it here using twilio.request_validator.RequestValidator
if TWILIO_WEBHOOK_SECRET is configured.  In production you must set
this variable.  Without it this endpoint is unauthenticated.
"""

import logging
from django.conf import settings
from django.http import HttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

logger = logging.getLogger(__name__)


def _get_twilio_backend_options() -> dict:
    """Return OPTIONS dict for the Twilio backend from settings.VOIP."""
    for backend in settings.VOIP:
        if backend.get("PROVIDER") == "Twilio":
            return backend.get("OPTIONS", {})
    return {}


def _validate_twilio_signature(request) -> bool:
    """
    Validate X-Twilio-Signature.
    Returns True if valid or if webhook_secret is not configured (dev mode).
    """
    options = _get_twilio_backend_options()
    auth_token = options.get("webhook_secret") or options.get("secret", "")

    if not auth_token:
        logger.warning(
            "TwilioTwiML: webhook_secret not set — skipping signature validation. "
            "Set TWILIO_WEBHOOK_SECRET in production."
        )
        return True

    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        # Build the full URL as Twilio sees it
        url = request.build_absolute_uri()
        signature = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
        # GET requests have no POST body params
        params = request.POST.dict() if request.method == "POST" else {}
        return validator.validate(url, params, signature)
    except ImportError:
        logger.warning(
            "twilio package not installed — cannot validate signature. "
            "Run: pip install twilio"
        )
        return True


@method_decorator(csrf_exempt, name="dispatch")
class TwilioTwiML(View):
    """
    Returns TwiML that dials the lead's number once the agent answers.

    GET ?to=+14045551234
    """

    def get(self, request, *args, **kwargs):
        if not _validate_twilio_signature(request):
            logger.warning("TwilioTwiML: invalid Twilio signature — rejected.")
            return HttpResponse("Forbidden", status=403)

        to_number = request.GET.get("to", "").strip()

        if not to_number:
            logger.error("TwilioTwiML called without ?to= parameter.")
            # Return a TwiML <Say> so the agent hears an error instead of silence
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response>"
                "<Say>Configuration error. The destination number is missing.</Say>"
                "</Response>"
            )
            return HttpResponse(twiml, content_type="application/xml", status=400)

        # Caller ID to show to the lead — use the Twilio number from settings
        options = _get_twilio_backend_options()
        caller_id = options.get("twilio_number", to_number)

        # Build the TwiML <Dial> response
        # callerId must be a verified/purchased Twilio number.
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Dial callerId="{caller_id}">'
            f"<Number>{to_number}</Number>"
            "</Dial>"
            "</Response>"
        )

        logger.info("TwilioTwiML: bridging call to %s", to_number)
        return HttpResponse(twiml, content_type="application/xml")
