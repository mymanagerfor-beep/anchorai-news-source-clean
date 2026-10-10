"""Provider abstraction for Gujarati TTS and talking-avatar generation (fal.ai queue inference)."""
import os
import time
from urllib.parse import urlparse

import requests

# Two credential modes (never mixed):
#  - "universal": EMERGENT_LLM_KEY via the Emergent proxy (queue inference only, not Fal Platform APIs)
#  - "fal_direct": the owner's FAL_KEY straight to queue.fal.run (for self-hosting on GitHub/cPanel/VPS)
PROXY_BASE = os.environ.get("INTEGRATION_PROXY_URL", "https://integrations.emergentagent.com").rstrip("/")
CONTROL_BASE = f"{PROXY_BASE}/api/v1/fal"
QUEUE_BASE = f"{CONTROL_BASE}/queue"
QUEUE_ORIGIN = "https://queue.fal.run"

TTS_ENDPOINT = "fal-ai/elevenlabs/tts/eleven-v3"
AVATAR_ENDPOINTS = {"fal_kling_v2_standard": "fal-ai/kling-video/ai-avatar/v2/standard"}

# Voices verified with a live Gujarati (language_code="gu") sample on eleven_v3.
GUJARATI_VOICES = [
    {"id": "Sarah", "label": "Sarah", "gender": "female", "tone": "Clear, confident newsreader"},
    {"id": "Laura", "label": "Laura", "gender": "female", "tone": "Warm, conversational"},
    {"id": "George", "label": "George", "gender": "male", "tone": "Deep, authoritative"},
    {"id": "Brian", "label": "Brian", "gender": "male", "tone": "Steady, neutral bulletin"},
]
VOICE_IDS = {v["id"] for v in GUJARATI_VOICES}


class ProviderError(Exception):
    def __init__(self, code, message, retry_safe=True):
        super().__init__(message)
        self.code, self.message, self.retry_safe = code, message, retry_safe


def mode():
    m = os.environ.get("AI_PROVIDER_MODE", "").strip().lower()
    if m in ("universal", "fal_direct"):
        return m
    return "fal_direct" if os.environ.get("FAL_KEY") else "universal"


def _key():
    return os.environ.get("FAL_KEY", "") if mode() == "fal_direct" else os.environ.get("EMERGENT_LLM_KEY", "")


def _headers(extra=None):
    if mode() == "fal_direct":
        h = {"Authorization": f"Key {_key()}", "Content-Type": "application/json"}
        h.update(extra or {})
        return h
    h = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}
    if os.environ.get("job_id"):
        h["X-App-ID"] = h["X-Job-ID"] = os.environ["job_id"]
    if extra:
        h.update(extra)
    return h


def _trusted(url):
    if mode() == "fal_direct":
        c = urlparse(url)
        if c.scheme != "https" or c.netloc != "queue.fal.run" or c.username:
            raise ProviderError("provider_bad_response", "The AI provider returned an unexpected response.")
        return url
    c, q = urlparse(url), urlparse(QUEUE_BASE)
    if c.scheme != q.scheme or c.netloc != q.netloc or c.username or c.fragment or not c.path.startswith(q.path + "/"):
        raise ProviderError("provider_bad_response", "The AI provider returned an unexpected response.")
    return url


def _raise_for(resp, stage):
    if resp.status_code < 400:
        return
    if resp.status_code == 402:
        raise ProviderError("provider_balance", "The platform's AI generation balance is exhausted. Your credits were "
                            "released. Please contact the administrator.", retry_safe=True)
    if resp.status_code in (401, 403):
        raise ProviderError("provider_auth", "The AI provider rejected the platform credentials. An administrator "
                            "must fix the provider configuration.", retry_safe=True)
    if resp.status_code == 429:
        raise ProviderError("provider_rate_limit", "The AI provider is rate-limiting requests. Please retry in a few "
                            "minutes.", retry_safe=True)
    if resp.status_code in (400, 422):
        raise ProviderError("provider_rejected", f"The AI provider rejected the {stage} request. Check the portrait "
                            "(clear, front-facing face) and script, then retry.", retry_safe=True)
    raise ProviderError("provider_error", f"The AI provider failed during {stage} (HTTP {resp.status_code}).")


class FalQueueAdapter:
    """Generic adapter: submit → status → result → cancel. Never auto-retries a submit."""
    name = "fal"

    def validate_configuration(self):
        if not _key():
            need = "FAL_KEY" if mode() == "fal_direct" else "EMERGENT_LLM_KEY (or FAL_KEY for direct fal.ai)"
            raise ProviderError("provider_not_configured", f"AI provider credentials are not configured. An "
                                f"administrator must set {need}.", retry_safe=False)

    def submit(self, endpoint, payload, stage):
        self.validate_configuration()
        try:
            if mode() == "fal_direct":
                r = requests.post(f"{QUEUE_ORIGIN}/{endpoint}", headers=_headers(), json=payload, timeout=60)
            else:
                r = requests.post(f"{CONTROL_BASE}/proxy",
                                  headers=_headers({"X-Fal-Target-Url": f"{QUEUE_ORIGIN}/{endpoint}"}),
                                  json=payload, timeout=60)
        except requests.RequestException:
            raise ProviderError("provider_unreachable", f"Could not reach the AI provider to start {stage}.")
        _raise_for(r, stage)
        s = r.json()
        return {"request_id": s.get("request_id"), "status_url": _trusted(s["status_url"]),
                "response_url": _trusted(s["response_url"]),
                "cancel_url": _trusted(s["cancel_url"]) if s.get("cancel_url") else None,
                "submitted_at": time.time()}

    def _get(self, url, timeout=30):
        delay = 1
        for attempt in range(5):
            try:
                return requests.get(url, headers=_headers(), timeout=timeout)
            except (requests.ConnectTimeout, requests.ReadTimeout, requests.ConnectionError):
                if attempt == 4:
                    raise ProviderError("provider_unreachable", "Lost connection to the AI provider while checking "
                                        "progress.")
                time.sleep(delay)
                delay *= 2

    def get_status(self, sub, stage):
        r = self._get(sub["status_url"])
        _raise_for(r, stage)
        body = r.json()
        st = (body.get("status") or "").upper()
        if st in {"FAILED", "ERROR", "CANCELLED", "CANCELED"} or (st in {"COMPLETED", "OK"} and body.get("error")):
            raise ProviderError("provider_failed", f"The AI provider could not complete {stage}. Try a clearer, "
                                "front-facing portrait or a shorter script.")
        return st

    def retrieve_output(self, sub, stage):
        r = self._get(sub["response_url"], timeout=60)
        _raise_for(r, stage)
        return r.json()

    def cancel_job(self, sub):
        if not sub or not sub.get("cancel_url"):
            return False
        try:
            return requests.put(sub["cancel_url"], headers=_headers(), timeout=20).status_code < 400
        except requests.RequestException:
            return False

    def verify_webhook(self, headers, body):
        # Universal-key mode does not deliver provider webhooks to the app; status is polled instead.
        return False


class GujaratiTTS(FalQueueAdapter):
    name = "fal_elevenlabs_v3"

    def validate_request(self, text, voice):
        if voice not in VOICE_IDS:
            raise ProviderError("unsupported_voice", "This voice is not verified for Gujarati.", retry_safe=False)
        if not text.strip() or len(text) > 5000:
            raise ProviderError("script_length", "Script is empty or longer than the provider limit (5000 chars).",
                                retry_safe=False)

    def create(self, text, voice):
        self.validate_request(text, voice)
        return self.submit(TTS_ENDPOINT, {"text": text, "voice": voice, "language_code": "gu", "timestamps": True,
                                          "stability": 0.5}, "Gujarati narration")

    @staticmethod
    def parse(result):
        audio = (result.get("audio") or {}).get("url")
        if not audio:
            raise ProviderError("provider_bad_response", "Narration finished without an audio file.")
        chars, starts, ends = [], [], []
        for chunk in result.get("timestamps") or []:
            if isinstance(chunk, dict):
                chars += chunk.get("characters") or []
                starts += chunk.get("character_start_times_seconds") or []
                ends += chunk.get("character_end_times_seconds") or []
        return audio, {"characters": chars, "starts": starts, "ends": ends}


class TalkingAvatar(FalQueueAdapter):
    def __init__(self, provider_key):
        self.name = provider_key
        self.endpoint = AVATAR_ENDPOINTS[provider_key]

    def estimate_cost_usd(self, seconds):
        return round(seconds * 0.0562, 3)

    def create(self, image_data_url, audio_url):
        return self.submit(self.endpoint, {"image_url": image_data_url, "audio_url": audio_url,
                                           "prompt": "A professional news anchor presenting the news to camera, "
                                                     "natural head movement, studio lighting"}, "talking-anchor video")

    @staticmethod
    def parse(result):
        url = (result.get("video") or {}).get("url")
        if not url:
            raise ProviderError("provider_bad_response", "The provider finished without a video file.")
        return url, result.get("duration")


def get_avatar_provider():
    key = os.environ.get("AVATAR_PROVIDER", "fal_kling_v2_standard")
    if key not in AVATAR_ENDPOINTS:
        raise ProviderError("provider_not_configured", f"Unknown AVATAR_PROVIDER '{key}'.", retry_safe=False)
    return TalkingAvatar(key)


def download(url, max_bytes=500 * 1024 * 1024, timeout=180):
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            buf = bytearray()
            for chunk in r.iter_content(1 << 20):
                buf += chunk
                if len(buf) > max_bytes:
                    raise ProviderError("download_failed", "Generated file is larger than allowed.")
            return bytes(buf)
    except requests.RequestException:
        raise ProviderError("download_failed", "Could not download the generated file from the provider.")


def health():
    out = {"provider": os.environ.get("AVATAR_PROVIDER", "fal_kling_v2_standard"), "tts": GujaratiTTS.name,
           "configured": bool(_key()), "mode": mode()}
    base = QUEUE_ORIGIN if mode() == "fal_direct" else f"{CONTROL_BASE}/queue"
    try:
        r = requests.get(f"{base}/fal-ai/elevenlabs/requests/healthcheck/status", headers=_headers(), timeout=15)
        out["reachable"] = r.status_code < 500
        out["auth_ok"] = r.status_code not in (401, 403)
        out["http_status"] = r.status_code
    except requests.RequestException:
        out["reachable"] = False
    return out
