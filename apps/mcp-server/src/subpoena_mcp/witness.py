"""Witness channels: Twilio (Messaging, Verify, Lookup) or a local simulator.

The simulator mirrors Twilio's behaviour closely enough for the demo and tests: outbound
messages land in the witness conversation log (shown in the Console's phone view), one-time
codes are delivered as SMS messages in that log, and SIM-swap data comes from the seed users.
Every outbound message is logged to the store in both modes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any, Protocol

import httpx

from subpoena_schemas import Channel, DeliveryStatus, MessageDirection, WitnessMessage, utcnow
from subpoena_store import Store, Verification

from .config import McpSettings
from .data import DataSource

CODE_TTL = timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 3


class WitnessChannel(Protocol):
    async def send_message(
        self, phone: str, body: str, channel: Channel, *, context: dict[str, Any]
    ) -> WitnessMessage: ...
    async def lookup(self, phone: str) -> dict[str, Any]: ...
    async def send_code(self, phone: str, *, context: dict[str, Any]) -> dict[str, Any]: ...
    async def check_code(self, phone: str, code: str) -> dict[str, Any]: ...


def _hash_code(phone: str, code: str) -> str:
    return hmac.new(phone.encode(), code.encode(), hashlib.sha256).hexdigest()


class SimulatorChannel:
    def __init__(self, store: Store, data: DataSource) -> None:
        self._store = store
        self._data = data

    async def send_message(
        self, phone: str, body: str, channel: Channel, *, context: dict[str, Any]
    ) -> WitnessMessage:
        msg = WitnessMessage(
            phone=phone,
            direction=MessageDirection.OUTBOUND,
            channel=channel,
            body=body,
            sid=f"SM{secrets.token_hex(16)}",
            status=DeliveryStatus.DELIVERED,
            **context,
        )
        await self._store.put_message(msg)
        return msg

    async def lookup(self, phone: str) -> dict[str, Any]:
        user = self._data.user_by_phone(phone) or {}
        hours = user.get("sim_swap_hours_ago")
        swapped = utcnow() - timedelta(hours=int(hours)) if hours is not None else None
        return {
            "phone": phone,
            "line_type": "mobile",
            "carrier": "Simulated Mobile",
            "last_sim_swap": swapped.isoformat() if swapped else None,
            "source": "simulator",
        }

    async def send_code(self, phone: str, *, context: dict[str, Any]) -> dict[str, Any]:
        code = f"{secrets.randbelow(10**6):06d}"
        await self._store.put_verification(
            Verification(
                phone=phone, code_hash=_hash_code(phone, code), expires_at=utcnow() + CODE_TTL
            )
        )
        await self.send_message(
            phone,
            f"Your verification code is {code}. It expires in 10 minutes. Never share it with anyone who calls you.",
            Channel.SMS,
            context=context,
        )
        return {"status": "pending", "channel": "sms"}

    async def check_code(self, phone: str, code: str) -> dict[str, Any]:
        v = await self._store.get_verification(phone)
        if v is None or v.expires_at < utcnow():
            return {"status": "expired"}
        if v.attempts >= MAX_CODE_ATTEMPTS:
            return {"status": "max_attempts_reached"}
        if hmac.compare_digest(v.code_hash, _hash_code(phone, code.strip())):
            await self._store.delete_verification(phone)
            return {"status": "approved"}
        v.attempts += 1
        await self._store.put_verification(v)
        return {"status": "pending", "attempts": v.attempts}


class TwilioChannel:
    """Twilio REST APIs via httpx (no SDK needed for these four calls)."""

    def __init__(self, store: Store, settings: McpSettings) -> None:
        assert settings.twilio_account_sid and settings.twilio_auth_token
        self._store = store
        self._s = settings
        self._http = httpx.AsyncClient(
            auth=(settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value()),
            timeout=15,
        )

    async def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        r = await self._http.post(url, data=data)
        r.raise_for_status()
        result: dict[str, Any] = r.json()
        return result

    async def send_message(
        self, phone: str, body: str, channel: Channel, *, context: dict[str, Any]
    ) -> WitnessMessage:
        s = self._s
        data: dict[str, str] = {}
        if channel is Channel.WHATSAPP:
            if not s.twilio_whatsapp_from:
                raise RuntimeError("WhatsApp sender not configured")
            data |= {"To": f"whatsapp:{phone}", "From": s.twilio_whatsapp_from}
            if s.twilio_whatsapp_content_sid:
                import json

                data |= {
                    "ContentSid": s.twilio_whatsapp_content_sid,
                    "ContentVariables": json.dumps({"1": body}),
                }
            else:
                data["Body"] = body
        else:
            if not s.twilio_messaging_service_sid:
                raise RuntimeError("SMS messaging service not configured")
            data |= {
                "To": phone,
                "MessagingServiceSid": s.twilio_messaging_service_sid,
                "Body": body,
            }
        if s.twilio_status_callback_url:
            data["StatusCallback"] = s.twilio_status_callback_url
        res = await self._post(
            f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json", data
        )
        msg = WitnessMessage(
            phone=phone,
            direction=MessageDirection.OUTBOUND,
            channel=channel,
            body=body,
            sid=res.get("sid"),
            status=DeliveryStatus.QUEUED,
            **context,
        )
        await self._store.put_message(msg)
        return msg

    async def lookup(self, phone: str) -> dict[str, Any]:
        r = await self._http.get(
            f"https://lookups.twilio.com/v2/PhoneNumbers/{phone}",
            params={"Fields": "line_type_intelligence,sim_swap"},
        )
        r.raise_for_status()
        body = r.json()
        swap = body.get("sim_swap") or {}
        period = (swap.get("last_sim_swap") or {}).get("swapped_period")
        # Twilio reports a coarse period (e.g. PT24H); convert to an approximate timestamp.
        last = None
        if period and period.startswith("PT") and period.endswith("H"):
            last = (utcnow() - timedelta(hours=int(period[2:-1]))).isoformat()
        return {
            "phone": phone,
            "line_type": (body.get("line_type_intelligence") or {}).get("type"),
            "carrier": (body.get("line_type_intelligence") or {}).get("carrier_name"),
            "last_sim_swap": last,
            "sim_swap_error": swap.get("error_code"),
            "source": "twilio",
        }

    async def send_code(self, phone: str, *, context: dict[str, Any]) -> dict[str, Any]:
        sid = self._s.twilio_verify_service_sid
        res = await self._post(
            f"https://verify.twilio.com/v2/Services/{sid}/Verifications",
            {"To": phone, "Channel": "sms"},
        )
        return {"status": res.get("status"), "channel": "sms"}

    async def check_code(self, phone: str, code: str) -> dict[str, Any]:
        sid = self._s.twilio_verify_service_sid
        try:
            res = await self._post(
                f"https://verify.twilio.com/v2/Services/{sid}/VerificationCheck",
                {"To": phone, "Code": code.strip()},
            )
        except httpx.HTTPStatusError as exc:
            # 404 = no pending verification (expired or max attempts)
            return {"status": "expired" if exc.response.status_code == 404 else "error"}
        return {"status": res.get("status")}
