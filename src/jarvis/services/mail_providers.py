from __future__ import annotations

import asyncio
import base64
import hashlib
import random
import re
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

import httpx

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": " ".join(
            [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            ]
        ),
        "api": "https://gmail.googleapis.com/gmail/v1/users/me",
    },
    "microsoft": {
        "authorize": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scope": "offline_access https://graph.microsoft.com/Mail.Read",
        "api": "https://graph.microsoft.com/v1.0/me",
    },
}


class MailError(RuntimeError):
    def __init__(self, message, *, code=""):
        super().__init__(message)
        self.code = code


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value, html=False):
    text = str(value or "")[:150_000]
    if html:
        parser = TextExtractor()
        parser.feed(text)
        text = " ".join(parser.parts)
    return re.sub(r"\s+", " ", text).strip()[:24_000]


def gmail_body(payload):
    if payload.get("filename"):
        return ""
    mime = payload.get("mimeType", "")
    if mime.startswith("multipart/"):
        children = payload.get("parts", [])
        preferred = [p for p in children if p.get("mimeType") == "text/plain"]
        return "\n".join(gmail_body(p) for p in (preferred or children))[:24_000]
    if mime not in {"text/plain", "text/html"}:
        return ""
    data = payload.get("body", {}).get("data", "")[:200_000]
    try:
        return plain(
            base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            ),
            mime == "text/html",
        )
    except ValueError:
        return ""


class MailProvider:
    def __init__(
        self,
        name,
        token,
        client,
        *,
        gmail_quota_units_per_minute=2400,
        max_retries=6,
        sleep=asyncio.sleep,
        jitter=random.random,
    ):
        self.name, self.token, self.client = name, token, client
        self.api = PROVIDERS[name]["api"]
        self.gmail_quota_units_per_minute = gmail_quota_units_per_minute
        self.max_retries = max_retries
        self.sleep = sleep
        self.jitter = jitter
        self.next_request = 0.0

    def quota_cost(self, url):
        if self.name != "google":
            return 0
        path = urlsplit(url).path.rstrip("/")
        if path.endswith("/profile"):
            return 1
        if path.endswith("/threads"):
            return 10
        if "/threads/" in path:
            return 40
        if path.endswith("/messages/send"):
            return 100
        return 1

    async def pace(self, cost):
        if not cost or self.gmail_quota_units_per_minute <= 0:
            return
        now = time.monotonic()
        if self.next_request > now:
            await self.sleep(self.next_request - now)
            now = time.monotonic()
        interval = 60 * cost / self.gmail_quota_units_per_minute
        self.next_request = max(self.next_request, now) + interval

    @staticmethod
    def error_details(response):
        try:
            error = response.json().get("error", {})
            errors = error.get("errors", [])
            reason = errors[0].get("reason", "") if errors else ""
            return reason, error.get("message", "")
        except (AttributeError, IndexError, TypeError, ValueError):
            return "", ""

    def retry_delay(self, response, attempt):
        try:
            header = float(response.headers.get("retry-after", ""))
        except (TypeError, ValueError):
            header = 0
        return max(1.0, min(64.0, header or 2**attempt + self.jitter()))

    async def get(self, url, params=None, extra_headers=None):
        expected = urlsplit(self.api)
        target = urlsplit(url)
        if (target.scheme, target.netloc) != (expected.scheme, expected.netloc):
            raise MailError("El proveedor devolvió un enlace de sincronización inválido")
        response = None
        reason = ""
        for attempt in range(self.max_retries + 1):
            await self.pace(self.quota_cost(url))
            try:
                response = await self.client.get(
                    url,
                    params=params,
                    headers={"Authorization": "Bearer " + self.token, **(extra_headers or {})},
                )
            except (httpx.NetworkError, httpx.TimeoutException):
                if attempt >= self.max_retries:
                    raise MailError(
                        "La conexión con el proveedor falló varias veces; se reintentará"
                    ) from None
                await self.sleep(min(64.0, 2**attempt + self.jitter()))
                continue
            reason, _ = self.error_details(response)
            limited = response.status_code == 429 or (
                response.status_code == 403
                and reason in {"rateLimitExceeded", "userRateLimitExceeded"}
            )
            temporary = response.status_code in {500, 502, 503, 504}
            if not limited and not temporary:
                break
            if attempt >= self.max_retries:
                if limited:
                    raise MailError(
                        "Gmail limitó temporalmente la lectura; Jarvis continuará poco a poco",
                        code=reason or "rateLimitExceeded",
                    )
                raise MailError(
                    "El proveedor no está disponible temporalmente; se reintentará",
                    code=reason or str(response.status_code),
                )
            await self.sleep(self.retry_delay(response, attempt))
        assert response is not None
        if response.status_code == 401:
            raise MailError("La sesión caducó; vuelve a conectar esta cuenta")
        if response.status_code == 403:
            if reason == "dailyLimitExceeded":
                raise MailError(
                    "Gmail alcanzó la cuota diaria del proyecto; se reintentará mañana",
                    code=reason,
                )
            raise MailError("El proveedor no autorizó la lectura; revisa permisos de la cuenta")
        if response.status_code == 429:
            raise MailError(
                "Gmail limitó temporalmente la lectura; Jarvis continuará poco a poco",
                code=reason or "rateLimitExceeded",
            )
        if not response.is_success:
            raise MailError(
                "No se pudo consultar el correo; se reintentará",
                code=reason or str(response.status_code),
            )
        if len(response.content) > 12_000_000:
            raise MailError("La respuesta del proveedor supera el límite de lectura")
        return response.json()

    async def post_once(self, url, payload):
        """Perform a non-retried mutation so an uncertain response cannot duplicate mail."""
        expected = urlsplit(self.api)
        target = urlsplit(url)
        if (target.scheme, target.netloc) != (expected.scheme, expected.netloc):
            raise MailError("El proveedor devolvió un destino de envío inválido")
        await self.pace(self.quota_cost(url))
        try:
            response = await self.client.post(
                url,
                json=payload,
                headers={"Authorization": "Bearer " + self.token},
            )
        except (httpx.NetworkError, httpx.TimeoutException):
            raise MailError(
                "No se pudo confirmar el envío. Revisa Gmail antes de volver a intentarlo",
                code="deliveryUnknown",
            ) from None
        reason, _ = self.error_details(response)
        if response.status_code == 401:
            raise MailError("La sesión caducó; vuelve a conectar esta cuenta")
        if response.status_code == 403:
            raise MailError(
                "Gmail no autorizó el envío. Reconecta la cuenta y concede el permiso de envío",
                code=reason or "forbidden",
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise MailError(
                "Gmail no confirmó el envío. Revisa el correo antes de reintentarlo",
                code=reason or str(response.status_code),
            )
        if not response.is_success:
            raise MailError("Gmail rechazó la respuesta; revisa el destinatario y el contenido")
        if len(response.content) > 1_000_000:
            raise MailError("La confirmación de Gmail supera el límite permitido")
        try:
            result = response.json()
        except ValueError as exc:
            raise MailError("Gmail devolvió una confirmación inválida") from exc
        if not isinstance(result, dict) or not result.get("id"):
            raise MailError("Gmail no confirmó el identificador del mensaje enviado")
        return result

    async def send_gmail_reply(self, raw_message: bytes, thread_id: str):
        if self.name != "google":
            raise MailError("Por ahora las respuestas autorizadas solo están disponibles en Gmail")
        if not raw_message or len(raw_message) > 500_000:
            raise MailError("La respuesta supera el límite permitido")
        return await self.post_once(
            self.api + "/messages/send",
            {
                "raw": base64.urlsafe_b64encode(raw_message).decode().rstrip("="),
                "threadId": thread_id,
            },
        )

    async def identity(self):
        if self.name == "google":
            return (await self.get(self.api + "/profile"))["emailAddress"]
        # User.Read identifies the mailbox owner; Mail.Read alone does not authorize /me.
        data = await self.get(self.api, {"$select": "mail,userPrincipalName"})
        return data.get("mail") or data["userPrincipalName"]

    async def gmail_page(self, since, page_token=None, max_results=20):
        if self.name != "google":
            raise MailError("La paginación de Gmail requiere una cuenta de Google")
        params = {"q": f"in:inbox after:{int(since)}", "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        listing = await self.get(self.api + "/threads", params)
        rows = []
        for thread in listing.get("threads", []):
            detail = await self.get(
                self.api + "/threads/" + quote(thread["id"], safe=""), {"format": "full"}
            )
            messages = [
                m
                for m in detail.get("messages", [])
                if not {"SENT", "DRAFT"}.intersection(m.get("labelIds", []))
            ]
            if not messages:
                continue
            parsed = []
            url = "https://mail.google.com/mail/u/0/#all/" + quote(thread["id"], safe="")
            for current in messages:
                payload = current.get("payload") or {}
                headers = {
                    h["name"].lower(): h["value"]
                    for h in payload.get("headers", [])
                    if h.get("name")
                }
                parsed.append(
                    {
                        "thread_id": thread["id"],
                        "version": current["id"],
                        "subject": plain(headers.get("subject", "Sin asunto"))[:300],
                        "sender": plain(headers.get("from", ""))[:300],
                        "received": datetime.fromtimestamp(
                            int(current.get("internalDate", 0)) / 1000, UTC
                        ).isoformat(),
                        "url": url,
                        "body": gmail_body(payload) or plain(current.get("snippet")),
                        "message_id": plain(headers.get("message-id", ""))[:500],
                        "reply_to": plain(
                            headers.get("reply-to", headers.get("from", ""))
                        )[:300],
                    }
                )
            latest = max(parsed, key=lambda item: item["received"])
            rows.append({**latest, "_thread_messages": parsed})
        return rows, listing.get("nextPageToken", "")

    async def messages(self, since):
        if self.name == "google":
            page_token = ""
            for _ in range(20):
                rows, page_token = await self.gmail_page(since, page_token, 50)
                for row in rows:
                    yield row
                if not page_token:
                    return
        else:
            timestamp = datetime.fromtimestamp(since, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            url = self.api + "/mailFolders/inbox/messages"
            params = {
                "$filter": f"receivedDateTime ge {timestamp}",
                "$top": 50,
                "$orderby": "receivedDateTime desc",
                "$select": (
                    "id,conversationId,subject,from,replyTo,internetMessageId,"
                    "receivedDateTime,body,webLink"
                ),
            }
            for _ in range(20):
                listing = await self.get(
                    url, params, {"Prefer": 'outlook.body-content-type="text"'}
                )
                for m in listing.get("value", []):
                    sender = m.get("from", {}).get("emailAddress", {})
                    link = m.get("webLink", "")
                    parsed = urlsplit(link)
                    if parsed.scheme != "https" or parsed.hostname not in {
                        "outlook.office.com",
                        "outlook.office365.com",
                        "outlook.live.com",
                    }:
                        link = "https://outlook.office.com/mail/"
                    yield {
                        "thread_id": m.get("conversationId") or m["id"],
                        "version": m["id"],
                        "subject": plain(m.get("subject", "Sin asunto"))[:300],
                        "sender": plain(f"{sender.get('name', '')} <{sender.get('address', '')}>")[
                            :300
                        ],
                        "received": datetime.fromisoformat(
                            m["receivedDateTime"].replace("Z", "+00:00")
                        ).isoformat(),
                        "url": link,
                        "body": plain(
                            m.get("body", {}).get("content", ""),
                            m.get("body", {}).get("contentType", "").lower() == "html",
                        ),
                        "message_id": plain(m.get("internetMessageId", ""))[:500],
                        "reply_to": plain(
                            (
                                (m.get("replyTo") or [{}])[0].get("emailAddress", {}).get("address")
                                if isinstance(m.get("replyTo"), list)
                                else sender.get("address", "")
                            )
                            or sender.get("address", "")
                        )[:300],
                    }
                url = listing.get("@odata.nextLink")
                params = None
                if not url:
                    return
        raise MailError("Hay más de 1000 conversaciones nuevas; la revisión está incompleta")


PROVIDERS["microsoft"]["scope"] += " https://graph.microsoft.com/User.Read"


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
