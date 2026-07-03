from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from html import escape
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Request, status
from models.schemas import ContactRequest, ContactResponse
from services.cache_store import cache_store

logger = logging.getLogger("lineuplab.contact")
router = APIRouter()

SUPPORT_EMAIL = "support@DiamScore.com"
CONTACT_SUBMISSIONS_KEY = "contact_submissions"
BREVO_SEND_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"


@router.post("/", response_model=ContactResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_contact(payload: ContactRequest, request: Request) -> ContactResponse:
    if payload.company:
        logger.info("Dropped contact form honeypot submission from %s", _client_ip(request))
        return ContactResponse(ok=True, message="Thanks. Your message has been received.")

    _store_contact_submission(payload, request)

    if _brevo_configured():
        try:
            _upsert_brevo_contact(payload)
            notify_email = os.getenv("BREVO_NOTIFY_EMAIL")
            if notify_email:
                _send_brevo_email(payload, request, notify_email)
        except RuntimeError as exc:
            logger.exception("Brevo contact sync failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
    else:
        logger.warning("Brevo is not configured; storing contact submission locally")

    return ContactResponse(ok=True, message="Thanks. Your message has been received.")


def _upsert_brevo_contact(payload: ContactRequest) -> None:
    list_id = _optional_int_env("BREVO_LIST_ID")
    body: dict[str, object] = {
        "email": str(payload.email),
        "updateEnabled": True,
    }
    if list_id:
        body["listIds"] = [list_id]
    status_code = _send_brevo_request(BREVO_CONTACTS_URL, body)
    logger.info("Brevo synced contact %s with HTTP %s", payload.email, status_code)


def _send_brevo_email(payload: ContactRequest, request: Request, notify_email: str) -> None:
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("BREVO_SENDER_EMAIL", SUPPORT_EMAIL)
    sender_name = os.getenv("BREVO_SENDER_NAME", "DiamScore")
    if not api_key:
        raise RuntimeError("Brevo API key is not configured.")
    subject = f"DiamScore contact: {payload.email}"
    plain_body = (
        "New DiamScore contact form submission\n\n"
        f"Email: {payload.email}\n"
        f"IP: {_client_ip(request)}\n"
        f"User-Agent: {request.headers.get('user-agent', 'unknown')}\n\n"
        f"Message:\n{payload.message or '(No message provided)'}\n"
    )
    html_body = f"""
    <h2>New DiamScore contact form submission</h2>
    <p><strong>Email:</strong> {escape(payload.email)}</p>
    <p><strong>IP:</strong> {escape(_client_ip(request))}</p>
    <p><strong>User-Agent:</strong> {escape(request.headers.get('user-agent', 'unknown'))}</p>
    <p><strong>Message:</strong></p>
    <pre style="white-space:pre-wrap;font-family:system-ui,sans-serif">{escape(payload.message or '(No message provided)')}</pre>
    """
    body = {
        "sender": {"email": sender_email, "name": sender_name},
        "to": [{"email": notify_email, "name": "DiamScore Support"}],
        "replyTo": {"email": str(payload.email)},
        "subject": subject,
        "textContent": plain_body,
        "htmlContent": html_body,
    }
    status_code = _send_brevo_request(BREVO_SEND_EMAIL_URL, body)
    logger.info("Brevo accepted contact notification email with HTTP %s", status_code)


def _send_brevo_request(url: str, body: dict[str, object]) -> int:
    api_key = os.getenv("BREVO_API_KEY")
    if not api_key:
        raise RuntimeError("Brevo API key is not configured.")
    request_body = json.dumps(body).encode("utf-8")
    brevo_request = UrlRequest(
        url,
        data=request_body,
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(brevo_request, timeout=10) as response:
            if response.status >= 400:
                raise RuntimeError(f"Brevo returned HTTP {response.status}")
            return response.status
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Brevo returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Brevo request failed: {exc.reason}") from exc


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def _brevo_configured() -> bool:
    return bool(os.getenv("BREVO_API_KEY"))


def _store_contact_submission(payload: ContactRequest, request: Request) -> None:
    data = cache_store.read_json(CONTACT_SUBMISSIONS_KEY, default=[])
    if not isinstance(data, list):
        data = []
    data.append(
        {
            "submitted_at": datetime.now(UTC).isoformat(),
            "email": str(payload.email),
            "message": payload.message,
            "ip": _client_ip(request),
            "user_agent": request.headers.get("user-agent", "unknown"),
        }
    )
    cache_store.write_json(CONTACT_SUBMISSIONS_KEY, data[-500:])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
