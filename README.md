# django-crm-twilio

Twilio VoIP integration for [django-crm](https://github.com/DjangoCRM/django-crm) — adds outbound callback calling, number pool rotation, and call logging to the existing Zadarma VoIP architecture, without modifying any upstream files outside `voip/`.

**Repo:** https://github.com/leadstartorg/django-crm-twilio  
**Maintained by:** [Leadstart Media, Inc.](https://leadstart.org)

---

## What This Does

When an agent clicks a phone number in the CRM, Twilio calls the **agent's phone first**, then bridges the agent to the **lead's phone** once the agent answers. The call is logged automatically in the Deal workflow when it ends.

```
Agent clicks ☎ in CRM → Twilio calls agent → agent answers → Twilio dials lead → call logged in CRM
```

This mirrors the existing Zadarma callback pattern exactly. Both providers coexist — each agent's Connection record selects which one they use.

---

## What's in This Repo

| File | Role |
|---|---|
| `twiliobackend_v2.py` | **Use this one.** Backend class with area-code pool rotation and structured logging. Copy to `voip/backends/twiliobackend.py`. |
| `twiliobackend.py` | v1 — single-number only, no logging. Superseded by v2. |
| `settings.py` | Replacement `voip/settings.py` — adds Twilio to the VOIP list alongside Zadarma |
| `models.py` | Replacement `voip/models.py` — adds `twilio_call_sid` field to Connection |
| `urls.py` | Replacement `voip/urls.py` — adds `/voip/twilio/twiml/` and `/voip/twilio/status/` routes |
| `twiml.py` | New view — returns TwiML `<Dial>` when Twilio fetches it after agent answers |
| `twiliowebhook.py` | New view — handles Twilio status events, logs calls in CRM |
| `0002_connection_twilio_call_sid.py` | Migration — adds `twilio_call_sid` column |
| `twilio_voip_complete.zip` | Complete drop-in package with all files in their correct directory structure |

---

## Quick Start

### 1. Install

```bash
pip install twilio
echo "twilio>=9.0" >> requirements.txt
```

### 2. Copy files from `twilio_voip_complete.zip`

Extract the zip and copy files to your project. The inner structure matches your django-crm layout:

```
voip/backends/twiliobackend.py          ← copy here (it's already v2 inside the zip)
voip/settings.py                        ← replace
voip/models.py                          ← replace
voip/urls.py                            ← replace
voip/views/twiml.py                     ← new file
voip/views/twiliowebhook.py             ← new file
voip/migrations/0002_connection_twilio_call_sid.py  ← new file
```

Files with **zero changes**: `callback.py`, `voipwebhook.py`, `admin.py`, `connectionform.py`, `zadarmabackend.py`, `webcrm/settings.py`, `webcrm/urls.py`

### 3. Set environment variables

Add to your `.env` file:

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_32_char_auth_token_here
TWILIO_WEBHOOK_SECRET=your_32_char_auth_token_here   # same as AUTH_TOKEN

TWILIO_NUMBER=+14045550100                            # your Twilio phone number

# Optional — number pool for area-code matched caller ID:
# TWILIO_NUMBER_POOL=+14041112222,+17701113333,+16781114444

TWILIO_TWIML_URL=https://yourcrm.com/voip/twilio/twiml/
TWILIO_STATUS_URL=https://yourcrm.com/voip/twilio/status/
```

### 4. Migrate

```bash
python manage.py migrate voip
```

### 5. Create a Connection in Django Admin

**Admin → VoIP → Connections → Add Connection**

| Field | Value |
|---|---|
| Provider | Twilio |
| Active | ✓ |
| Number | Agent's phone in E.164 (`+14045550199`) |
| Owner | Agent's Django user |

### 6. Test

Click a phone number on any Lead or Contact. Your phone should ring within 10 seconds.

---

## Number Pool Rotation

v2 supports area-code matched number pools to improve answer rates. Set `TWILIO_NUMBER_POOL` as a comma-separated list of Twilio numbers you own. When a call goes out, the backend selects the number whose area code best matches the lead's number.

```bash
TWILIO_NUMBER_POOL=+14041112222,+17701113333,+16781114444
```

Django logs show the selection:

```
DEBUG TwilioAPI: area-code 404 matched → selected +14041112222 from pool ['+14041112222']
INFO  TwilioAPI: call initiated — SID CA... | from=+14045550199 to=+14045551234 via pool=+14041112222
```

Pool is optional. If empty, falls back to `TWILIO_NUMBER`.

---

## Google Voice (Optional)

Google Voice cannot be integrated server-side (no public API). This repo includes a client-side link integration that opens Google Voice in the browser with the lead's number pre-filled — identical in approach to the existing Viber and WhatsApp links.

Apply the 3 edits described in `twilio_complete/crm/site/crmmodeladmin_google_voice_patch.py`. No backend code, no credentials, no migration needed.

After the edit, the phone column menu in Lead/Contact/Deal admin shows:

```
+14045551234
  ┌─────────────────────────────────┐
  │ Callback to smartphone          │  ← Twilio or Zadarma
  │ Viber chat                      │  ← viber://
  │ WhatsApp chat                   │  ← wa.me/
  │ Google Voice call               │  ← voice.google.com  (new)
  └─────────────────────────────────┘
```

---

## Architecture

```
voip/
├── settings.py          — VOIP list: Zadarma + Twilio (reads from env vars)
├── models.py            — Connection model + twilio_call_sid field
├── urls.py              — routes: /get-callback/ /zd/ /twilio/twiml/ /twilio/status/
├── backends/
│   ├── zadarmabackend.py     — original (unchanged)
│   └── twiliobackend.py      — NEW: TwilioAPI with pool rotation
├── views/
│   ├── callback.py           — original ConnectionView (unchanged)
│   ├── voipwebhook.py        — original Zadarma webhook (unchanged)
│   ├── twiml.py              — NEW: TwilioTwiML — returns <Dial> XML
│   └── twiliowebhook.py      — NEW: TwilioWebHook — logs calls in CRM
└── migrations/
    ├── 0001_initial.py       — original (unchanged)
    └── 0002_connection_twilio_call_sid.py  — NEW: adds twilio_call_sid
```

Integration points outside `voip/` that are **not modified**:
- `webcrm/settings.py` — existing `from voip.settings import *` picks up Twilio automatically
- `webcrm/urls.py` — existing `include('voip.urls')` picks up new routes automatically
- `crm/site/crmmodeladmin.py` — 3 optional edits for Google Voice links only

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Popup: "Twilio provider not found" | Replace `voip/settings.py` with the one in this package |
| Popup: "No caller ID available" | Set `TWILIO_NUMBER` in `.env` |
| Popup: "Error! 21212" | Connection `number` must be E.164: `+14045550199` |
| Popup shows success but phone never rings | Connection `number` must be the agent's actual phone |
| Agent answers, lead never rings | Check `TWILIO_TWIML_URL` is public HTTPS; test with curl |
| Webhook 403 | `TWILIO_WEBHOOK_SECRET` must equal your Auth Token exactly |
| No call log in Deal | Check `TWILIO_STATUS_URL` is reachable; lead must have E.164 phone stored |
| `ImportError: No module named 'twilio'` | `pip install twilio` |
| `OperationalError: no such column twilio_call_sid` | `python manage.py migrate voip` |

---

## Local Development

Twilio cannot reach localhost. Use [ngrok](https://ngrok.com/download):

```bash
# Terminal 1
python manage.py runserver 8000

# Terminal 2
ngrok http 8000
# Prints: https://abc123.ngrok-free.app → localhost:8000
```

Set your `.env`:
```bash
TWILIO_TWIML_URL=https://abc123.ngrok-free.app/voip/twilio/twiml/
TWILIO_STATUS_URL=https://abc123.ngrok-free.app/voip/twilio/status/
```

Restart Django after each `.env` change. Free ngrok URLs reset on each restart.

---

## Full Installation Guide

See [`TWILIO_VOIP_INSTALL_GUIDE_v2.md`](./TWILIO_VOIP_INSTALL_GUIDE_v2.md) for the complete step-by-step guide with all troubleshooting, endpoint testing procedures, CRM log verification, and production hardening checklist.

---

## License

GNU General Public License v3.0 — same as the upstream django-crm project. See `LICENSE`.
