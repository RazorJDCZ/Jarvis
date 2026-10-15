"""Opt-in Web Push. Browser subscriptions remain scoped to authenticated devices."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from datetime import datetime
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from jarvis.services.mail_providers import MailError
from jarvis.services.organizer import TZ


class WebPush:
    def __init__(self, organizer, remote_access):
        self.organizer, self.remote = organizer, remote_access
        self.store = organizer.store
        self.worker = None

    def keys(self):
        secrets = self.organizer.mail.store
        keys = secrets.secret("webpush:vapid")
        if not keys:
            key = ec.generate_private_key(ec.SECP256R1())
            private = key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            public = key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
            keys = {
                "private": base64.urlsafe_b64encode(private).decode().rstrip("="),
                "public": base64.urlsafe_b64encode(public).decode().rstrip("="),
            }
            secrets.save_secret("webpush:vapid", keys)
        return keys

    def subscribe(self, subscription, session, device=""):
        endpoint = subscription.get("endpoint", "")
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        permitted = host in {
            "fcm.googleapis.com",
            "updates.push.services.mozilla.com",
            "web.push.apple.com",
        } or host.endswith(".push.apple.com")
        if (
            parsed.scheme != "https"
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not permitted
            or len(endpoint) > 2048
        ):
            raise MailError("Proveedor de avisos no admitido. Usa Chrome, Firefox o Safari")
        keys = subscription.get("keys", {})
        try:

            def decode(s):
                return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

            if len(decode(keys["auth"])) != 16:
                raise ValueError()
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode(keys["p256dh"]))
        except (ValueError, KeyError, TypeError):
            raise MailError("Suscripción de avisos inválida") from None
        identifier = hashlib.sha256(endpoint.encode()).hexdigest()
        previous = self.store.get("subscription", identifier)
        if previous and previous["session"] != session:
            raise MailError("La suscripción pertenece a otra sesión")
        if not previous and len(self.store.list("subscription")) >= 20:
            raise MailError("Se alcanzó el límite de dispositivos")
        self.store.put(
            "subscription",
            identifier,
            {
                "id": identifier,
                "session": session,
                "device": device,
                "subscription": {"endpoint": endpoint, "keys": keys},
                "since": time.time(),
                "error": "",
            },
        )
        if self.organizer.capabilities:
            self.organizer.capabilities.outbox.register(session)
        return {"id": identifier}

    async def start(self):
        self.worker = asyncio.create_task(self._loop())

    async def close(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)

    async def _loop(self):
        while True:
            try:
                await self.deliver()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(15)

    def send(self, subscription, payload):
        import requests
        from pywebpush import webpush

        class FixedSession(requests.Session):
            def request(self, method, url, **kwargs):
                kwargs["allow_redirects"] = False
                return super().request(method, url, **kwargs)

        with FixedSession() as client:
            client.trust_env = False
            response = webpush(
                subscription_info=subscription,
                data=json.dumps(payload),
                vapid_private_key=self.keys()["private"],
                vapid_claims={"sub": self.organizer.config.remote_origin or "https://localhost"},
                ttl=3600,
                timeout=10,
                requests_session=client,
            )
            if not 200 <= response.status_code < 300:
                raise MailError("El proveedor rechazó el aviso")

    async def _deliver_appa(self, capabilities):
        connectors = getattr(capabilities, "connectors", None)
        if connectors is None:
            return
        try:
            connector = connectors.require_appa()
        except Exception:
            return
        from jarvis.services.organizer import APPA_DESKTOP_SESSION

        for item in capabilities.outbox.pending(APPA_DESKTOP_SESSION):
            identifier = item.get("notification_id")
            body = (
                "Tu resumen diario está listo para revisar."
                if item.get("event") == "briefing"
                else " ".join(str(item.get("title", "Tienes un pendiente para revisar.")).split())
            )
            if not isinstance(identifier, str) or not body:
                continue
            try:
                await connector.send_notification("Jarvis", body[:500], identifier)
            except Exception:
                break
            capabilities.outbox.acknowledge(APPA_DESKTOP_SESSION, [identifier])

    async def deliver(self):
        capabilities = self.organizer.capabilities
        if not capabilities or capabilities.preferences.quiet(datetime.now(TZ).hour):
            return
        await self._deliver_appa(capabilities)
        for subscription in self.store.list("subscription"):
            if subscription["device"] and not self.remote.get_device(subscription["device"]):
                self.store.delete("subscription", subscription["id"])
                continue
            from jarvis.services.organizer import inbox_session

            sessions = {subscription["session"]} | {
                s
                for s in capabilities.outbox.sessions()
                if inbox_session(s) == subscription["session"]
            }
            pending = []
            for session in sessions:
                offset = 0
                while True:
                    batch = capabilities.outbox.pending(
                        session, after=subscription["since"] - 2, offset=offset
                    )
                    pending.extend(batch)
                    if len(batch) < 100:
                        break
                    offset += 100
            for item in pending:
                try:
                    if (
                        datetime.fromisoformat(item["created_at"]).timestamp()
                        < subscription["since"] - 2
                    ):
                        continue
                except (KeyError, ValueError):
                    continue
                key = subscription["id"] + ":" + item["notification_id"]
                attempt = self.store.get("push_delivery", key, {})
                if attempt.get("sent") or attempt.get("retry", 0) > time.time():
                    continue
                try:
                    # Lock-screen content is private by default; details need the authenticated app.
                    await asyncio.to_thread(
                        self.send,
                        subscription["subscription"],
                        {
                            "title": "Jarvis",
                            "body": "Tienes un pendiente o recordatorio para revisar.",
                            "tag": item["notification_id"],
                            "url": "/organizer",
                        },
                    )
                    self.store.put("push_delivery", key, {"sent": time.time()})
                    self.store.put(
                        "subscription", subscription["id"], {**subscription, "error": ""}
                    )
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    if status is None and getattr(exc, "response", None) is not None:
                        status = exc.response.status_code
                    if status in (404, 410):
                        self.store.delete("subscription", subscription["id"])
                        break
                    failures = attempt.get("failures", 0) + 1
                    self.store.put(
                        "push_delivery",
                        key,
                        {
                            "failures": failures,
                            "retry": time.time() + min(3600, 30 * 2 ** min(failures, 7)),
                        },
                    )
                    self.store.put(
                        "subscription",
                        subscription["id"],
                        {**subscription, "error": "El aviso no se pudo entregar; se reintentará"},
                    )
                    break
