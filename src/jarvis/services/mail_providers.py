from __future__ import annotations

import base64
import hashlib
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
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
    pass


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
    def __init__(self, name, token, client):
        self.name, self.token, self.client = name, token, client
        self.api = PROVIDERS[name]["api"]

    async def get(self, url, params=None, extra_headers=None):
        expected = urlsplit(self.api)
        target = urlsplit(url)
        if (target.scheme, target.netloc) != (expected.scheme, expected.netloc):
            raise MailError("El proveedor devolvió un enlace de sincronización inválido")
        response = await self.client.get(
            url,
            params=params,
            headers={"Authorization": "Bearer " + self.token, **(extra_headers or {})},
        )
        if response.status_code == 401:
            raise MailError("La sesión caducó; vuelve a conectar esta cuenta")
        if response.status_code == 403:
            raise MailError("El proveedor no autorizó la lectura; revisa permisos de la cuenta")
        if response.status_code == 429:
            raise MailError("El proveedor limitó las consultas; se reintentará en unos minutos")
        if not response.is_success:
            raise MailError("No se pudo consultar el correo; se reintentará")
        if len(response.content) > 12_000_000:
            raise MailError("La respuesta del proveedor supera el límite de lectura")
        return response.json()

    async def identity(self):
        if self.name == "google":
            return (await self.get(self.api + "/profile"))["emailAddress"]
        # User.Read identifies the mailbox owner; Mail.Read alone does not authorize /me.
        data = await self.get(self.api, {"$select": "mail,userPrincipalName"})
        return data.get("mail") or data["userPrincipalName"]

    async def messages(self, since):
        if self.name == "google":
            params = {"q": f"in:inbox after:{int(since)}", "maxResults": 50}
            for _ in range(20):
                listing = await self.get(self.api + "/threads", params)
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
                    latest = max(messages, key=lambda m: int(m.get("internalDate", 0)))
                    headers = {
                        h["name"].lower(): h["value"] for h in latest["payload"].get("headers", [])
                    }
                    body = gmail_body(latest["payload"]) or plain(latest.get("snippet"))
                    yield {
                        "thread_id": thread["id"],
                        "version": latest["id"],
                        "subject": plain(headers.get("subject", "Sin asunto"))[:300],
                        "sender": plain(headers.get("from", ""))[:300],
                        "received": datetime.fromtimestamp(
                            int(latest["internalDate"]) / 1000, UTC
                        ).isoformat(),
                        "url": "https://mail.google.com/mail/u/0/#all/"
                        + quote(thread["id"], safe=""),
                        "body": body,
                    }
                if not listing.get("nextPageToken"):
                    return
                params["pageToken"] = listing["nextPageToken"]
        else:
            timestamp = datetime.fromtimestamp(since, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            url = self.api + "/mailFolders/inbox/messages"
            params = {
                "$filter": f"receivedDateTime ge {timestamp}",
                "$top": 50,
                "$orderby": "receivedDateTime desc",
                "$select": "id,conversationId,subject,from,receivedDateTime,body,webLink",
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
                    }
                url = listing.get("@odata.nextLink")
                params = None
                if not url:
                    return
        raise MailError("Hay más de 1000 conversaciones nuevas; la revisión está incompleta")


PROVIDERS["microsoft"]["scope"] += " https://graph.microsoft.com/User.Read"


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
