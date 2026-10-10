"""Breaking News composition: Pillow (HarfBuzz/raqm shaping for Gujarati) renders graphics, FFmpeg composes."""
import re
import json
import subprocess
import datetime
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONT = Path(__file__).parent / "fonts" / "NotoSansGujarati.ttf"
W, H = 1920, 1080
SAFE_X, SAFE_Y = 96, 54
DISCLOSURE = "AI દ્વારા બનાવાયેલ પ્રસ્તુતકર્તા વિડિયો · AI-generated presenter video"
GU_MONTHS = ["જાન્યુઆરી", "ફેબ્રુઆરી", "માર્ચ", "એપ્રિલ", "મે", "જૂન", "જુલાઈ", "ઑગસ્ટ", "સપ્ટેમ્બર", "ઑક્ટોબર",
             "નવેમ્બર", "ડિસેમ્બર"]
GU_DIGITS = str.maketrans("0123456789", "૦૧૨૩૪૫૬૭૮૯")


class RenderError(Exception):
    pass


def gujarati_date(d=None):
    d = d or datetime.date.today()
    return f"{str(d.day).translate(GU_DIGITS)} {GU_MONTHS[d.month - 1]} {str(d.year).translate(GU_DIGITS)}"


def font(size, weight=700):
    f = ImageFont.truetype(str(FONT), size, layout_engine=ImageFont.Layout.RAQM)
    try:
        f.set_variation_by_axes([weight, 100])
    except Exception:
        pass
    return f


def hex_rgb(h, default=(220, 38, 38)):
    h = (h or "").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return default
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def text_w(f, s):
    if not s:
        return 0
    b = f.getbbox(s)
    return b[2] - b[0]


def fit_font(s, max_w, size, min_size=24, weight=700):
    while size > min_size:
        f = font(size, weight)
        if text_w(f, s) <= max_w:
            return f
        size -= 2
    return font(min_size, weight)


def wrap(s, f, max_w, max_lines=2):
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_w(f, t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:max_lines]


# ---------- subtitles ----------

def split_cues(script, max_chars=64):
    sentences = [s.strip() for s in re.split(r"(?<=[।.!?॥])\s+|\n+", script) if s.strip()]
    cues = []
    for s in sentences:
        words, cur = s.split(), ""
        for w in words:
            if len(cur) + len(w) + 1 > max_chars and cur:
                cues.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            cues.append(cur)
    return cues


def apply_pronunciation(text, pairs):
    for p in pairs or []:
        word, say = (p.get("word") or "").strip(), (p.get("say") or "").strip()
        if word and say:
            text = re.sub(rf"(?<![\w\u0A80-\u0AFF]){re.escape(word)}(?![\w\u0A80-\u0AFF])", say, text)
    return text


def build_spoken(script, pairs):
    cues = split_cues(script)
    spoken = [apply_pronunciation(c, pairs) for c in cues]
    return cues, spoken, " ".join(spoken)


def time_cues(cues, spoken, alignment, audio_duration):
    """Phrase-level timing from character timestamps; proportional fallback when alignment is unusable."""
    chars = alignment.get("characters") or []
    starts, ends = alignment.get("starts") or [], alignment.get("ends") or []
    nonspace = [(c, s, e) for c, s, e in zip(chars, starts, ends) if not c.isspace()]
    counts = [len(re.sub(r"\s", "", s)) for s in spoken]
    total = sum(counts)
    out, method = [], "character_timestamps"
    if nonspace and total and abs(len(nonspace) - total) <= max(3, total * 0.05):
        idx = 0
        for cue, n in zip(cues, counts):
            a = nonspace[min(idx, len(nonspace) - 1)][1]
            b = nonspace[min(idx + n - 1, len(nonspace) - 1)][2]
            out.append({"text": cue, "start": round(a, 3), "end": round(max(b, a + 0.4), 3)})
            idx += n
    else:
        method = "proportional_estimate"
        t = 0.0
        for cue, n in zip(cues, counts):
            d = audio_duration * (n / total) if total else 0
            out.append({"text": cue, "start": round(t, 3), "end": round(t + d, 3)})
            t += d
    for i in range(len(out) - 1):
        out[i]["end"] = min(out[i]["end"], out[i + 1]["start"]) if out[i + 1]["start"] > out[i]["start"] else out[i]["end"]
    return out, method


def _ts(t, sep):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def to_srt(cues, offset=0.0):
    return "\n".join(f"{i}\n{_ts(c['start'] + offset, ',')} --> {_ts(c['end'] + offset, ',')}\n{c['text']}\n"
                     for i, c in enumerate(cues, 1))


def to_vtt(cues, offset=0.0):
    return "WEBVTT\n\n" + "\n".join(f"{_ts(c['start'] + offset, '.')} --> {_ts(c['end'] + offset, '.')}\n{c['text']}\n"
                                     for c in cues)


def validate_cues(cues, duration):
    for c in cues:
        if c["start"] < 0 or c["end"] <= c["start"] or c["end"] > duration + 1.0:
            raise RenderError("Subtitle timing validation failed.")


# ---------- graphics ----------

def draw_backdrop(primary, secondary):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    base = (11, 15, 25)
    p = hex_rgb(primary)
    for y in range(H):
        k = y / H
        col = tuple(int(base[i] * (1 - 0.18 * k) + p[i] * 0.10 * (1 - k)) for i in range(3))
        d.line([(0, y), (W, y)], fill=col)
    for x in range(0, W, 120):
        d.line([(x, 0), (x, H)], fill=(24, 34, 50), width=1)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([W // 2 - 640, 40, W // 2 + 640, 900], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img.paste(Image.new("RGB", (W, H), hex_rgb(secondary, (31, 43, 62))), (0, 0), glow)
    return img


def corner_xy(corner, w, h):
    x = SAFE_X if "left" in corner else W - SAFE_X - w
    y = SAFE_Y if "top" in corner else 700 - h
    return x, y


def draw_overlay(b, logo_img=None):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    primary, secondary = hex_rgb(b.get("primary_color")), hex_rgb(b.get("secondary_color"), (15, 23, 42))
    corner = b.get("logo_corner") or "top-right"
    if logo_img is not None:
        lg = logo_img.copy()
        lg.thumbnail((220, 120))
        ov.alpha_composite(lg, corner_xy(corner, lg.width, lg.height))
    elif b.get("channel_name"):
        f = fit_font(b["channel_name"], 360, 40)
        tw = text_w(f, b["channel_name"])
        x, y = corner_xy(corner, tw + 40, 64)
        d.rounded_rectangle([x, y, x + tw + 40, y + 64], 8, fill=primary + (235,))
        d.text((x + 20, y + 32), b["channel_name"], font=f, fill="white", anchor="lm")
    # disclosure pill on opposite top corner
    fd = font(24, 600)
    dw = text_w(fd, DISCLOSURE) + 36
    dx = SAFE_X if "right" in corner else W - SAFE_X - dw
    d.rounded_rectangle([dx, SAFE_Y, dx + dw, SAFE_Y + 44], 22, fill=(0, 0, 0, 170), outline=(255, 255, 255, 90))
    d.text((dx + 18, SAFE_Y + 22), DISCLOSURE, font=fd, fill=(255, 255, 255, 240), anchor="lm")
    # lower third
    y0 = 800
    banner = (b.get("banner_text") or "BREAKING NEWS").upper()[:30]
    fb = font(34, 800)
    bw = text_w(fb, banner) + 48
    d.rectangle([SAFE_X, y0, SAFE_X + bw, y0 + 58], fill=primary + (255,))
    d.text((SAFE_X + 24, y0 + 29), banner, font=fb, fill="white", anchor="lm")
    x = SAFE_X + bw
    loc = (b.get("location") or "").strip()
    if loc:
        fl = font(28, 600)
        lw = text_w(fl, loc) + 44
        d.rectangle([x, y0, x + lw, y0 + 58], fill=(255, 255, 255, 255))
        d.text((x + 22, y0 + 29), loc, font=fl, fill=(17, 24, 39), anchor="lm")
        x += lw
    if b.get("show_date"):
        fdt = font(26, 500)
        ds = gujarati_date()
        dtw = text_w(fdt, ds) + 40
        d.rectangle([x, y0, x + dtw, y0 + 58], fill=(17, 24, 39, 235))
        d.text((x + 20, y0 + 29), ds, font=fdt, fill=(229, 231, 235), anchor="lm")
    headline = (b.get("headline") or "").strip()
    d.rectangle([SAFE_X, y0 + 58, W - SAFE_X, y0 + 148], fill=secondary + (255,))
    d.rectangle([SAFE_X, y0 + 58, SAFE_X + 10, y0 + 148], fill=primary + (255,))
    if headline:
        fh = fit_font(headline, W - 2 * SAFE_X - 60, 50, 30, 700)
        d.text((SAFE_X + 36, y0 + 103), headline, font=fh, fill="white", anchor="lm")
    return ov


def draw_ticker_parts(b):
    """Returns (bar+label mask image placed at y=970, scrolling text strip or None)."""
    primary = hex_rgb(b.get("primary_color"))
    label = (b.get("ticker_label") or "તાજા સમાચાર").strip()[:24]
    fl = font(28, 800)
    lw = text_w(fl, label) + 48
    bar = Image.new("RGBA", (W, 56), (0, 0, 0, 0))
    d = ImageDraw.Draw(bar)
    d.rectangle([0, 0, SAFE_X + lw, 56], fill=primary + (255,))
    d.text((SAFE_X + 24, 28), label, font=fl, fill="white", anchor="lm")
    text = (b.get("ticker_text") or "").strip()
    if not b.get("ticker_enabled", True) or not text:
        return bar, None, SAFE_X + lw
    ft = font(30, 600)
    s = "   •   ".join([t.strip() for t in text.split("\n") if t.strip()]) + "   •   "
    tw = text_w(ft, s) + 40
    strip = Image.new("RGBA", (tw, 56), (0, 0, 0, 0))
    ImageDraw.Draw(strip).text((20, 28), s, font=ft, fill="white", anchor="lm")
    return bar, strip, SAFE_X + lw


def ticker_background():
    bg = Image.new("RGBA", (W, 56), (9, 12, 20, 235))
    ImageDraw.Draw(bg).line([(0, 0), (W, 0)], fill=(239, 68, 68, 255), width=2)
    return bg


def draw_cue(text, style):
    size = int(style.get("size") or 42)
    f = font(size, 600)
    lines = wrap(text, f, 1500)
    color = hex_rgb(style.get("color"), (255, 255, 255))
    lh = int(size * 1.6)
    widths = [text_w(f, ln) for ln in lines]
    bw, bh = max(widths) + 56, lh * len(lines) + 24
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if (style.get("background") or "box") == "box":
        d.rounded_rectangle([0, 0, bw, bh], 10, fill=(0, 0, 0, 175))
        for i, ln in enumerate(lines):
            d.text((bw // 2, 12 + lh * i + lh // 2), ln, font=f, fill=color + (255,), anchor="mm")
    else:
        for i, ln in enumerate(lines):
            d.text((bw // 2, 12 + lh * i + lh // 2), ln, font=f, fill=color + (255,), anchor="mm",
                   stroke_width=4, stroke_fill=(0, 0, 0, 255))
    return img


def cue_y(style, h):
    return 120 if style.get("position") == "top" else 790 - h


def draw_card(b, logo_img, title):
    img = draw_backdrop(b.get("primary_color"), b.get("secondary_color")).convert("RGBA")
    d = ImageDraw.Draw(img)
    primary = hex_rgb(b.get("primary_color"))
    y = 330
    if logo_img is not None:
        lg = logo_img.copy()
        lg.thumbnail((420, 220))
        img.alpha_composite(lg, ((W - lg.width) // 2, y))
        y += lg.height + 40
    name = b.get("channel_name") or ""
    if name:
        f = fit_font(name, 1400, 84)
        d.text((W // 2, y + 50), name, font=f, fill="white", anchor="mm")
        y += 120
    fb = font(36, 800)
    tw = text_w(fb, title) + 60
    d.rectangle([(W - tw) // 2, y + 10, (W + tw) // 2, y + 70], fill=primary + (255,))
    d.text((W // 2, y + 40), title, font=fb, fill="white", anchor="mm")
    fd = font(26, 600)
    d.text((W // 2, H - SAFE_Y - 30), DISCLOSURE, font=fd, fill=(229, 231, 235), anchor="mm")
    return img.convert("RGB")


# ---------- ffmpeg ----------

def run(args, timeout=900):
    try:
        p = subprocess.run([FFMPEG, "-hide_banner", "-y", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RenderError("Rendering timed out (insufficient rendering resources).")
    if p.returncode != 0:
        raise RenderError("FFmpeg failed: " + p.stderr.strip().splitlines()[-1][:300] if p.stderr.strip() else
                          "FFmpeg failed")
    return p


def probe(path):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60)
    err = p.stderr
    info = {"duration": None, "width": None, "height": None, "video_codec": None, "has_audio": False,
            "audio_codec": None}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.search(r"Stream #\S+.*Video: (\w+).*?, (\d{2,5})x(\d{2,5})", err)
    if m:
        info["video_codec"], info["width"], info["height"] = m[1], int(m[2]), int(m[3])
    m = re.search(r"Stream #\S+.*Audio: (\w+)", err)
    if m:
        info["has_audio"], info["audio_codec"] = True, m[1]
    return info


def decodes(path):
    p = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    return p.returncode == 0 and not p.stderr.strip()


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-profile:v", "high",
       "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def render_card(png, out, seconds=3):
    run(["-loop", "1", "-t", str(seconds), "-i", str(png), "-f", "lavfi", "-t", str(seconds), "-i",
         "anullsrc=r=48000:cl=stereo", "-vf", f"fps=30,fade=in:0:12,fade=out:st={seconds - 0.4}:d=0.4,format=yuv420p",
         *ENC, "-shortest", str(out)])


def render_final(workdir: Path, anchor_mp4: Path, narration: Path, branding: dict, cues: list, subtitle_style: dict,
                 logo_bytes: bytes = None):
    workdir.mkdir(parents=True, exist_ok=True)
    src = probe(anchor_mp4)
    if not src["duration"] or not src["width"]:
        raise RenderError("The generated anchor video could not be read.")
    dur = src["duration"]
    logo = None
    if logo_bytes and branding.get("branding_enabled", True):
        from io import BytesIO
        logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
    b = branding if branding.get("branding_enabled", True) else {**branding, "channel_name": "", "headline":
                                                                  branding.get("headline")}
    draw_backdrop(b.get("primary_color"), b.get("secondary_color")).save(workdir / "bg.png")
    draw_overlay(b, logo).save(workdir / "overlay.png")
    ticker_background().save(workdir / "tbg.png")
    bar, strip, text_x0 = draw_ticker_parts(b)
    inputs = ["-loop", "1", "-i", str(workdir / "bg.png"), "-i", str(anchor_mp4)]
    audio_idx = 1
    if not src["has_audio"]:
        inputs += ["-i", str(narration)]
        audio_idx = 2
    n = audio_idx + 1
    inputs += ["-loop", "1", "-i", str(workdir / "overlay.png"), "-loop", "1", "-i", str(workdir / "tbg.png")]
    i_ov, i_tbg = n, n + 1
    n += 2
    fg = [f"[1:v]scale=w=1500:h=900:force_original_aspect_ratio=decrease,setsar=1[a]",
          f"[0:v][a]overlay=x=(W-w)/2:y=30:shortest=1[v0]", f"[v0][{i_ov}:v]overlay=0:0[v1]",
          f"[v1][{i_tbg}:v]overlay=0:970[v2]"]
    last = "v2"
    if strip is not None:
        strip.save(workdir / "strip.png")
        bar.save(workdir / "bar.png")
        inputs += ["-loop", "1", "-i", str(workdir / "strip.png"), "-loop", "1", "-i", str(workdir / "bar.png")]
        span = W - text_x0
        fg += [f"[{last}][{n}:v]overlay=x='{text_x0}+{span}-mod(t*150\\,w+{span})':y=970[v3]",
               f"[v3][{n + 1}:v]overlay=0:970[v4]"]
        last, n = "v4", n + 2
    else:
        bar.save(workdir / "bar.png")
        inputs += ["-loop", "1", "-i", str(workdir / "bar.png")]
        fg.append(f"[{last}][{n}:v]overlay=0:970[v4]")
        last, n = "v4", n + 1
    if subtitle_style.get("enabled", True):
        for k, c in enumerate(cues):
            img = draw_cue(c["text"], subtitle_style)
            p = workdir / f"cue{k}.png"
            img.save(p)
            inputs += ["-loop", "1", "-i", str(p)]
            y = cue_y(subtitle_style, img.height)
            fg.append(f"[{last}][{n}:v]overlay=x=(W-w)/2:y={y}:enable='between(t,{c['start']},{c['end']})'[s{k}]")
            last, n = f"s{k}", n + 1
    fg.append(f"[{last}]format=yuv420p[vout]")
    main = workdir / "main.mp4"
    (workdir / "graph.txt").write_text(";".join(fg))
    run([*inputs, "-filter_complex_script", str(workdir / "graph.txt"), "-map", "[vout]", "-map", f"{audio_idx}:a",
         "-t", f"{dur:.3f}", *ENC, "-movflags", "+faststart", str(main)])
    parts, offset = [], 0.0
    if branding.get("intro_enabled"):
        draw_card(b, logo, (b.get("banner_text") or "BREAKING NEWS").upper()).save(workdir / "intro.png")
        render_card(workdir / "intro.png", workdir / "intro.mp4")
        parts.append(workdir / "intro.mp4")
        offset = 3.0
    parts.append(main)
    if branding.get("outro_enabled"):
        draw_card(b, logo, "આભાર · Thank you").save(workdir / "outro.png")
        render_card(workdir / "outro.png", workdir / "outro.mp4")
        parts.append(workdir / "outro.mp4")
    final = workdir / "final.mp4"
    if len(parts) == 1:
        final = main
    else:
        (workdir / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
        run(["-f", "concat", "-safe", "0", "-i", str(workdir / "list.txt"), "-c", "copy", "-movflags", "+faststart",
             str(final)])
    expected = dur + (3.0 if branding.get("intro_enabled") else 0) + (3.0 if branding.get("outro_enabled") else 0)
    return final, verify_output(final, expected), offset


def verify_output(path: Path, expected):
    if not path.exists() or path.stat().st_size < 50_000:
        raise RenderError("Rendered file is missing or truncated.")
    info = probe(path)
    if (info["width"], info["height"]) != (W, H):
        raise RenderError("Rendered video dimensions do not match 1920×1080.")
    if info["video_codec"] != "h264" or not info["has_audio"] or info["audio_codec"] != "aac":
        raise RenderError("Rendered video is missing an H.264 video or AAC audio stream.")
    if not info["duration"] or abs(info["duration"] - expected) > 2.0:
        raise RenderError("Rendered video duration is not plausible.")
    if not decodes(path):
        raise RenderError("Rendered video failed the decode check.")
    info["file_size"] = path.stat().st_size
    return info


def preview_frame(branding, subtitle_style, sample_cue, logo_bytes=None, portrait_bytes=None):
    """Static composition preview (not the generated video)."""
    from io import BytesIO
    bg = draw_backdrop(branding.get("primary_color"), branding.get("secondary_color")).convert("RGBA")
    if portrait_bytes:
        p = Image.open(BytesIO(portrait_bytes)).convert("RGBA")
        p.thumbnail((1500, 900))
        bg.alpha_composite(p, ((W - p.width) // 2, 30))
    logo = Image.open(BytesIO(logo_bytes)).convert("RGBA") if logo_bytes else None
    bg.alpha_composite(draw_overlay(branding, logo))
    bg.alpha_composite(ticker_background(), (0, 970))
    bar, strip, x0 = draw_ticker_parts(branding)
    if strip is not None:
        bg.alpha_composite(strip.crop((0, 0, min(strip.width, W - x0), 56)), (x0, 970))
        bg.alpha_composite(bar, (0, 970))
    else:
        bg.alpha_composite(bar, (0, 970))
    if sample_cue and subtitle_style.get("enabled", True):
        c = draw_cue(sample_cue, subtitle_style)
        bg.alpha_composite(c, ((W - c.width) // 2, cue_y(subtitle_style, c.height)))
    out = BytesIO()
    bg.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue()


def dumps(o):
    return json.dumps(o, ensure_ascii=False)
