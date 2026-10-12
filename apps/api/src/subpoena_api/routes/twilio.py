"""Twilio webhooks and the witness simulator (Spec §6 Testimony Processing, steps 1-2).

Inbound messages are matched to the witness's open subpoena by phone number. A 6-digit code
in the message is held for the Bailiff to verify; any other text is the (untrusted) reply.
The courtroom is then nudged over ``subpoena.activity``; nothing here interprets the text.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from subpoena_schemas import (
    ApiKey,
    Channel,
    DeliveryStatus,
    MessageDirection,
    Model,
    Scope,
    WitnessMessage,
)

from ..deps import Services, ServicesDep, require
from ..problems import ProblemError

router = APIRouter(tags=["witness"])

CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """https://www.twilio.com/docs/usage/webhooks/webhooks-security"""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def split_message(body: str) -> tuple[str | None, str | None]:
    """Return (code, reply_text) from a witness message."""
    m = CODE.search(body)
    code = m.group(1) if m else None
    text = CODE.sub(" ", body).strip(" .,-:\n\t") if m else body.strip()
    return code, (text or None)


async def record_inbound(
    services: Services, phone: str, body: str, channel: Channel, sid: str | None
) -> dict[str, object]:
    sub = await services.store.find_open_subpoena(phone)
    await services.store.put_message(
        WitnessMessage(
            workspace_id=sub.workspace_id if sub else None,
            subpoena_id=sub.id if sub else None,
            evaluation_id=sub.evaluation_id if sub else None,
            phone=phone,
            direction=MessageDirection.INBOUND,
            channel=channel,
            body=body[:2000],
            sid=sid,
            status=DeliveryStatus.DELIVERED,
        )
    )
    if sub is None:
        return {"matched": False}
    code, text = split_message(body)
    if code:
        sub.pending_code = code
    if text:
        sub.reply_text = f"{sub.reply_text}\n{text}" if sub.reply_text else text
    await services.store.put_subpoena(sub)
    await services.publisher.publish_subpoena_activity(sub.id)
    return {
        "matched": True,
        "subpoena_id": sub.id,
        "code_received": bool(code),
        "text_received": bool(text),
    }


@router.post("/v1/webhooks/twilio/inbound", include_in_schema=False)
async def twilio_inbound(request: Request, services: ServicesDep) -> Response:
    params = await _verified_form(request, services)
    sender = params.get("From", "")
    channel = Channel.WHATSAPP if sender.startswith("whatsapp:") else Channel.SMS
    phone = sender.removeprefix("whatsapp:")
    await record_inbound(services, phone, params.get("Body", ""), channel, params.get("MessageSid"))
    return Response(EMPTY_TWIML, media_type="application/xml")


@router.post("/v1/webhooks/twilio/status", include_in_schema=False)
async def twilio_status(request: Request, services: ServicesDep) -> Response:
    params = await _verified_form(request, services)
    sid, status = params.get("MessageSid"), params.get("MessageStatus", "").upper()
    if sid and status in DeliveryStatus.__members__:
        await services.store.update_message_status(sid, status)
    return Response(status_code=204)


async def _verified_form(request: Request, services: Services) -> dict[str, str]:
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    token = services.settings.twilio_auth_token
    if token is None:
        raise ProblemError(503, "twilio-not-configured", "Twilio webhooks are not enabled")
    url = services.settings.public_base_url.rstrip("/") + request.url.path
    expected = twilio_signature(token.get_secret_value(), url, params)
    if not hmac.compare_digest(expected, request.headers.get("x-twilio-signature", "")):
        raise ProblemError(403, "invalid-signature", "Twilio signature validation failed")
    return params


class SimulatedReply(Model):
    phone: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    body: str = Field(min_length=1, max_length=1000)
    channel: Channel = Channel.WHATSAPP


@router.post("/v1/simulator/witness-reply")
async def simulator_reply(
    body: SimulatedReply,
    key: Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_OVERRIDE))],
    services: ServicesDep,
) -> dict[str, object]:
    """Console phone simulator: behaves exactly like an inbound Twilio message."""
    if not services.settings.witness_simulator:
        raise ProblemError(404, "not-found", "Witness simulator is disabled")
    sub = await services.store.find_open_subpoena(body.phone)
    if sub is not None and sub.workspace_id != key.workspace_id:
        raise ProblemError(404, "not-found", "No open subpoena for this number in your workspace")
    return await record_inbound(services, body.phone, body.body, body.channel, sid=None)
