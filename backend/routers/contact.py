from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from models.schemas import ContactRequest, ContactResponse
from services.cache_store import cache_store

logger = logging.getLogger("lineuplab.contact")
router = APIRouter()

SUPPORT_EMAIL = "support@DiamScore.com"
CONTACT_SUBMISSIONS_KEY = "contact_submissions"


@router.post("/", response_model=ContactResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_contact(payload: ContactRequest, request: Request) -> ContactResponse:
    if payload.company:
        logger.info("Dropped contact form honeypot submission from %s", _client_ip(request))
        return ContactResponse(ok=True, message="Thanks. Your message has been received.")

    if _smtp_configured():
        try:
            _send_support_email(payload, request)
        except RuntimeError as exc:
            logger.exception("Contact email delivery failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
    else:
        _store_contact_submission(payload, request)

    return ContactResponse(ok=True, message="Thanks. Your message has been received.")


def _send_support_email(payload: ContactRequest, request: Request) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or SUPPORT_EMAIL)
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() != "false"

    if not smtp_host or not smtp_user or not smtp_password:
        raise RuntimeError("Email delivery is not configured.")

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

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = SUPPORT_EMAIL
    message["Reply-To"] = payload.email
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
        if smtp_use_tls:
            server.starttls(context=context)
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def _smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


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
