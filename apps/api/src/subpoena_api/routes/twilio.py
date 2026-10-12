"""Twilio webhooks and the witness simulator (Spec §6 Testimony Processing, steps 1-2).

Inbound messages are matched to the witness's open subpoena by phone number. A 6-digit code
in the message is held for the Bailiff to verify; any other text is the (untrusted) reply;
photos (e.g. a receipt) go to the media store for the courtroom's receipt check.
The courtroom is then nudged over ``subpoena.activity``; nothing here interprets the content.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import re
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, model_validator

from subpoena_schemas import (
    ApiKey,
    Channel,
    DeliveryStatus,
    MediaRef,
    MessageDirection,
    Model,
    Scope,
    WitnessMessage,
)

from ..deps import Services, ServicesDep, require
from ..problems import ProblemError

router = APIRouter(tags=["witness"])
log = logging.getLogger(__name__)

IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")
MAX_PHOTOS = 3

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


async def store_media(
    services: Services, workspace_id: str, photos: list[tuple[bytes, str]], source: str
) -> list[MediaRef]:
    refs = []
    for data, ctype in photos[:MAX_PHOTOS]:
        ref = MediaRef(
            content_type=ctype,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            source=source,
        )
        await services.media.put(f"{workspace_id}/{ref.id}", data, ctype)
        refs.append(ref)
    return refs


async def record_inbound(
    services: Services,
    phone: str,
    body: str,
    channel: Channel,
    sid: str | None,
    photos: list[tuple[bytes, str]] | None = None,
    source: str = "twilio",
) -> dict[str, object]:
    sub = await services.store.find_open_subpoena(phone)
    media = await store_media(services, sub.workspace_id, photos or [], source) if sub else []
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
            media=media,
        )
    )
    if sub is None:
        return {"matched": False}
    code, text = split_message(body)
    if code:
        sub.pending_code = code
    if text:
        sub.reply_text = f"{sub.reply_text}\n{text}" if sub.reply_text else text
    sub.media.extend(media)
    await services.store.put_subpoena(sub)
    await services.publisher.publish_subpoena_activity(sub.id)
    return {
        "matched": True,
        "subpoena_id": sub.id,
        "code_received": bool(code),
        "text_received": bool(text),
        "photos_received": len(media),
    }


async def twilio_photos(services: Services, params: dict[str, str]) -> list[tuple[bytes, str]]:
    """Download image attachments. Twilio media URLs need the account's credentials."""
    s = services.settings
    count = int(params.get("NumMedia", "0") or 0)
    if not count:
        return []
    if not (s.twilio_account_sid and s.twilio_auth_token):
        log.warning("photo received but SUBPOENA_TWILIO_ACCOUNT_SID is not set; ignoring it")
        return []
    photos = []
    auth = (s.twilio_account_sid, s.twilio_auth_token.get_secret_value())
    async with httpx.AsyncClient(auth=auth, follow_redirects=True, timeout=20) as http:
        for i in range(min(count, MAX_PHOTOS)):
            url = params.get(f"MediaUrl{i}", "")
            ctype = params.get(f"MediaContentType{i}", "").lower()
            # Only fetch from Twilio itself (the webhook is signed, but never follow arbitrary URLs).
            if ctype not in IMAGE_TYPES or not url.startswith("https://api.twilio.com/"):
                continue
            r = await http.get(url)
            if r.is_success and len(r.content) <= s.max_media_bytes:
                photos.append((r.content, ctype))
    return photos


@router.post("/v1/webhooks/twilio/inbound", include_in_schema=False)
async def twilio_inbound(request: Request, services: ServicesDep) -> Response:
    params = await _verified_form(request, services)
    sender = params.get("From", "")
    channel = Channel.WHATSAPP if sender.startswith("whatsapp:") else Channel.SMS
    phone = sender.removeprefix("whatsapp:")
    photos = await twilio_photos(services, params)
    await record_inbound(
        services, phone, params.get("Body", ""), channel, params.get("MessageSid"), photos
    )
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


class SimulatedPhoto(Model):
    content_type: str = Field(pattern=r"^image/(jpeg|png|webp|heic|heif)$")
    data_base64: str = Field(max_length=7_000_000)


class SimulatedReply(Model):
    phone: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    body: str = Field(default="", max_length=1000)
    channel: Channel = Channel.WHATSAPP
    photos: list[SimulatedPhoto] = Field(default_factory=list, max_length=MAX_PHOTOS)

    @model_validator(mode="after")
    def _not_empty(self) -> SimulatedReply:
        if not self.body.strip() and not self.photos:
            raise ValueError("send a message, a photo or both")
        return self


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
    photos = []
    for p in body.photos:
        try:
            data = base64.b64decode(p.data_base64, validate=True)
        except binascii.Error as exc:
            raise ProblemError(422, "invalid-photo", "Photo is not valid base64") from exc
        if len(data) > services.settings.max_media_bytes:
            raise ProblemError(413, "photo-too-large", "Photos must be 5 MB or smaller")
        photos.append((data, p.content_type))
    return await record_inbound(
        services, body.phone, body.body, body.channel, sid=None, photos=photos, source="simulator"
    )


@router.get("/v1/media/{media_id}", include_in_schema=False)
async def get_media(
    media_id: str,
    request: Request,
    key: Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_READ))],
    services: ServicesDep,
) -> Response:
    """A witness photo, scoped to the caller's workspace by its storage key."""
    if getattr(request.state, "mask_pii", False):
        raise ProblemError(403, "masked", "Witness photos are hidden from viewers")
    if not re.fullmatch(r"med_[a-z0-9]+", media_id):
        raise ProblemError(404, "not-found", "Photo not found")
    found = await services.media.get(f"{key.workspace_id}/{media_id}")
    if found is None:
        raise ProblemError(404, "not-found", "Photo not found")
    data, ctype = found
    return Response(data, media_type=ctype, headers={"cache-control": "private, max-age=3600"})
