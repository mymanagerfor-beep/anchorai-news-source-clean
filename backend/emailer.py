import os
import re
import ipaddress
import logging
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

import asyncio
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

import httpx

logger = logging.getLogger("anchorai.email")
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME = os.environ["EMAIL_FROM_NAME"]
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")
# "emergent" (managed) or "smtp" (e.g. cPanel mailbox) or "none"
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "emergent").lower()


def email_configured():
    if EMAIL_BACKEND == "smtp":
        return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))
    return EMAIL_BACKEND == "emergent" and bool(EMAIL_KEY)


def _smtp_send(to, subject, html):
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"], msg["To"] = subject, to
    msg["From"] = formataddr((EMAIL_FROM_NAME, os.environ["SMTP_FROM"]))
    if EMAIL_REPLY_TO:
        msg["Reply-To"] = EMAIL_REPLY_TO
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465"))
    sec = os.environ.get("SMTP_SECURITY", "ssl").lower()
    ctx = ssl.create_default_context()
    srv = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) if sec == "ssl" else smtplib.SMTP(host, port, timeout=30)
    with srv:
        if sec == "starttls":
            srv.starttls(context=ctx)
        if os.environ.get("SMTP_USER"):
            srv.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        srv.sendmail(os.environ["SMTP_FROM"], [to], msg.as_string())

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")


async def send_email(*, to: str, subject: str, html: str) -> bool:
    """Returns True when accepted. Failures are logged; callers decide how to surface them."""
    _assert_safe_email(subject, html)
    if EMAIL_BACKEND == "smtp":
        try:
            await asyncio.to_thread(_smtp_send, to, subject, html)
            return True
        except Exception as e:
            logger.error("SMTP send failed: %s", type(e).__name__)
            return False
    if EMAIL_BACKEND == "none" or not EMAIL_KEY:
        logger.warning("Email not configured (EMERGENT_EMAIL_KEY missing)")
        return False
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if EMAIL_REPLY_TO:
        payload["contact_email"] = EMAIL_REPLY_TO
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(f"{EMAIL_BASE_URL}/api/v1/email/send", headers={"X-Email-Key": EMAIL_KEY}, json=payload)
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        try:
            code = e.response.json().get("code", "")
        except ValueError:
            code = ""
        logger.warning("Email send refused: %s %s", e.response.status_code, code)
        return False
    except Exception as e:
        logger.error("Email send error: %s", type(e).__name__)
        return False


def _template(title: str, body_html: str, cta_text: str = None, cta_url: str = None) -> str:
    cta = ""
    if cta_url:
        cta = (f'<p style="margin:24px 0"><a href="{escape(cta_url)}" style="background:#DC2626;color:#ffffff;'
               f'padding:12px 20px;border-radius:6px;text-decoration:none;font-weight:bold">{escape(cta_text)}</a></p>')
    return (f'<table role="presentation" width="100%" style="background:#0B0F19"><tr><td style="padding:32px;'
            f'font-family:Arial,sans-serif;color:#F9FAFB"><p style="color:#EF4444;font-weight:bold;letter-spacing:2px">'
            f'{escape(EMAIL_FROM_NAME).upper()}</p><h2 style="color:#ffffff">{escape(title)}</h2>{body_html}{cta}'
            f'<p style="font-size:12px;color:#9CA3AF">Sent by {escape(EMAIL_FROM_NAME)}. We never ask for your password '
            f'or card details by email.</p></td></tr></table>')


async def send_verification(to, name, url):
    html = _template("Verify your email", f"<p>Hi {escape(name)}, confirm your email address to activate your "
                     f"workspace and unlock your trial credits. This link expires in 24 hours.</p>", "Verify email", url)
    return await send_email(to=to, subject=f"Verify your {EMAIL_FROM_NAME} account", html=html)


async def send_reset(to, name, url):
    html = _template("Reset your password", f"<p>Hi {escape(name)}, we received a request to reset your password. "
                     f"The link expires in 1 hour. If you did not request this, you can ignore this email.</p>",
                     "Choose a new password", url)
    return await send_email(to=to, subject=f"Reset your {EMAIL_FROM_NAME} password", html=html)


async def send_video_ready(to, name, project_name, url):
    html = _template("Your news video is ready", f"<p>Hi {escape(name)}, the video for project "
                     f"<strong>{escape(project_name)}</strong> finished rendering and is available in your library.</p>",
                     "Open video library", url)
    return await send_email(to=to, subject=f"Video ready: {project_name}", html=html)
