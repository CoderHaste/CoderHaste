#!/usr/bin/env python3
"""Render the profile README cards as animated SVGs.

    python scripts/render_cards.py            # animated cards -> cards/{light,dark}/
    STATIC=1 python scripts/render_cards.py   # final frame only (for screenshots)

Reads cards.config.json and data/github.json (written daily by
scripts/fetch_data.py). If the data file is missing, deterministic sample data
is used and every data card is stamped "SAMPLE DATA".

Everything here must survive being shown through an <img> tag on GitHub:
no scripts, no external requests. So we use an inline <style> with CSS
keyframes, a few SMIL <animate> loops, and Inter subset with pyftsubset
(fontTools) and embedded as base64 WOFF data URIs.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import random
from collections import OrderedDict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cards"
STATIC = os.environ.get("STATIC") == "1"
CONFIG = json.loads((ROOT / "cards.config.json").read_text())

# ── Palette: lifted from the A-OBD web dashboard (ather-obd-monitor) ──────────
THEMES = {
    "light": dict(
        surface="#ffffff", surface2="#f1f3f0", text="#16201b", muted="#69746d",
        line="#e4e7e3", track="#e6e9e5", accent="#1d7a57", accent2="#3fae84",
        accent_soft="#e2f1e9", warn="#b87408", warn_soft="#fbf0d9",
        icon_bg="#1d7a57", icon_fg="#ffffff",
        heat=["#e6e9e5", "#b5dcc7", "#6fbf98", "#2f9468", "#1d7a57"],
    ),
    "dark": dict(
        surface="#171c19", surface2="#1e2521", text="#eef2ef", muted="#93a198",
        line="#262e29", track="#262e29", accent="#4cc38f", accent2="#3fae84",
        accent_soft="#1f3a2d", warn="#e5a93d", warn_soft="#3a3020",
        icon_bg="#3fae84", icon_fg="#ffffff",
        heat=["#222a25", "#1f4a36", "#2a7552", "#3aa476", "#4cc38f"],
    ),
}

FONT_FILES = {500: "Inter-Medium.otf", 700: "Inter-Bold.otf", 800: "Inter-ExtraBold.otf"}
_FONTS = {w: TTFont(ROOT / "fonts" / f) for w, f in FONT_FILES.items()}
_CMAPS = {w: f.getBestCmap() for w, f in _FONTS.items()}
_HMTX = {w: f["hmtx"] for w, f in _FONTS.items()}
_UPM = {w: f["head"].unitsPerEm for w, f in _FONTS.items()}
_WOFF_CACHE: dict = {}

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


# ── Text measurement + font subsetting ───────────────────────────────────────
def measure(s: str, size: float, weight: int = 500, ls_em: float = 0.0) -> float:
    cmap, hmtx, upm = _CMAPS[weight], _HMTX[weight], _UPM[weight]
    adv = 0
    for ch in s:
        g = cmap.get(ord(ch)) or cmap.get(ord("?"))
        adv += hmtx[g][0]
    return adv * size / upm + ls_em * size * len(s)


def woff_b64(weight: int, chars: str) -> str:
    key = (weight, chars)
    if key not in _WOFF_CACHE:
        opts = subset.Options()
        opts.flavor = "woff"
        opts.layout_features = ["kern", "liga", "calt"]
        opts.name_IDs = []
        opts.notdef_outline = False
        opts.hinting = False
        opts.desubroutinize = True
        font = TTFont(ROOT / "fonts" / FONT_FILES[weight])
        sub = subset.Subsetter(opts)
        sub.populate(text=chars)
        sub.subset(font)
        buf = io.BytesIO()
        font.flavor = "woff"
        font.save(buf)
        _WOFF_CACHE[key] = base64.b64encode(buf.getvalue()).decode()
    return _WOFF_CACHE[key]


# ── SVG builder ──────────────────────────────────────────────────────────────
class Card:
    """Collects markup, used glyphs and keyframes for one SVG."""

    def __init__(self, w: int, h: int, theme: str, base: float = 0.0, title: str = "", gap: int = 14):
        # `gap` is transparent space under the card so stacked <img>s don't touch on GitHub
        self.w, self.h, self.base, self.title, self.gap = w, h, base, title, gap
        self.c = THEMES[theme]
        self.body: list[str] = []
        self.chars: dict[int, set] = {500: set(), 700: set(), 800: set()}
        self.keyframes: "OrderedDict[str, str]" = OrderedDict()

    # animation helpers -------------------------------------------------------
    def anim(self, name: str, delay: float, dur: float = 0.7, ease: str = "cubic-bezier(.2,.8,.2,1)") -> str:
        """Return a style attribute for a one-shot animation (empty when STATIC)."""
        if STATIC:
            return ""
        return f' style="animation:{name} {dur:.2f}s {ease} {self.base + delay:.2f}s both"'

    def keyframe(self, name: str, body: str) -> str:
        self.keyframes[name] = body
        return name

    def add(self, s: str) -> None:
        self.body.append(s)

    # primitives --------------------------------------------------------------
    def text(self, x, y, s, size, weight=500, fill="text", anchor="start", ls=0.0, extra="", raw=False):
        s = str(s)
        self.chars[weight].update(s)
        ls_attr = f' letter-spacing="{ls * size:.2f}"' if ls else ""
        anc = "" if anchor == "start" else f' text-anchor="{anchor}"'
        fill_c = self.c.get(fill, fill)
        content = s if raw else escape(s)
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
                f'fill="{fill_c}"{anc}{ls_attr}{extra}>{content}</text>')

    def label(self, x, y, s, anchor="start", fill="muted", size=11):
        return self.text(x, y, s.upper(), size, 700, fill, anchor, ls=0.09)

    def value(self, x, y, num, unit, size=30, anchor="start", fill="text", unit_ratio=0.5, extra=""):
        """Big numeral with a small muted unit, like the dashboard's '54.82 v'."""
        num, unit = str(num), str(unit)
        self.chars[800].update(num)
        self.chars[700].update(unit)
        anc = "" if anchor == "start" else f' text-anchor="{anchor}"'
        u = (f'<tspan font-size="{size * unit_ratio:.1f}" font-weight="700" fill="{self.c["muted"]}" '
             f'dx="{size * 0.12:.1f}">{escape(unit)}</tspan>') if unit else ""
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="800" '
                f'letter-spacing="{-0.03 * size:.2f}" fill="{self.c[fill]}"{anc}{extra}>{escape(num)}{u}</text>')

    def pill(self, x, y, s, fill="accent_soft", color="accent", size=12, pad=10, h=24, anchor="start"):
        w = measure(s, size, 700) + pad * 2
        if anchor == "end":
            x -= w
        elif anchor == "middle":
            x -= w / 2
        return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="{h / 2}" fill="{self.c[fill]}"/>'
                + self.text(x + w / 2, y + h / 2 + size * 0.36, s, size, 700, color, "middle")), w

    def surface(self, pad=1):
        return (f'<rect x="{pad / 2}" y="{pad / 2}" width="{self.w - pad}" height="{self.h - pad}" rx="22" '
                f'fill="{self.c["surface"]}" stroke="{self.c["line"]}" stroke-width="{pad}"/>')

    def sample_stamp(self, data, x=None, y=22):
        if not data.get("sample"):
            return ""
        x = self.w - 24 if x is None else x
        p, _ = self.pill(x, y - 15, "SAMPLE DATA", "warn_soft", "warn", size=10, pad=8, h=20, anchor="end")
        return p

    def live_dot(self, cx, cy, r=4, color="accent"):
        col = self.c[color]
        loop = ""
        if not STATIC:
            loop = (f'<circle class="loop" cx="{cx}" cy="{cy}" r="{r}" fill="{col}" opacity="0">'
                    f'<animate attributeName="r" values="{r};{r * 3}" dur="1.8s" repeatCount="indefinite"/>'
                    f'<animate attributeName="opacity" values=".45;0" dur="1.8s" repeatCount="indefinite"/>'
                    f'</circle>')
        return loop + f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{col}"/>'

    # output ------------------------------------------------------------------
    def render(self) -> str:
        faces = []
        for w in (500, 700, 800):
            chars = "".join(sorted(self.chars[w]))
            if chars:
                faces.append(f"@font-face{{font-family:'Card';font-weight:{w};"
                             f"src:url(data:font/woff;base64,{woff_b64(w, chars)}) format('woff')}}")
        css = [*faces,
               "text{font-family:'Card',Inter,system-ui,-apple-system,'Segoe UI',sans-serif;"
               "font-kerning:normal}"]
        if not STATIC:
            css += [
                "@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}",
                "@keyframes fade{from{opacity:0}to{opacity:1}}",
                "@keyframes grow{from{transform:scaleY(0)}to{transform:none}}",
                "@keyframes growx{from{transform:scaleX(0)}to{transform:none}}",
                "@keyframes pop{0%{opacity:0;transform:scale(0)}70%{opacity:1;transform:scale(1.25)}100%{transform:none}}",
                "@keyframes draw{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}",
                *[f"@keyframes {k}{{{v}}}" for k, v in self.keyframes.items()],
                ".gy,.gx,.gc{transform-box:fill-box}",
                ".gy{transform-origin:50% 100%}.gx{transform-origin:0 50%}.gc{transform-origin:50% 50%}",
                "@media (prefers-reduced-motion:reduce){*{animation:none!important}.loop{display:none}}",
            ]
        title = f"<title>{escape(self.title)}</title>" if self.title else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{self.w}" height="{self.h + self.gap}" viewBox="0 0 {self.w} {self.h + self.gap}" role="img">'
                f'{title}<style>{"".join(css)}</style>{"".join(self.body)}</svg>\n')


# ── Icons (24×24, drawn for this project) ────────────────────────────────────
ICONS = {
    "bolt": '<path d="M13.2 2.5 5 13.6h6.1l-1.3 7.9 8.2-11.1h-6.1z" fill="{fg}"/>',
    "trend": ('<path d="M3.5 17.5 9 12l3.5 3.5 7.5-8" fill="none" stroke="{fg}" stroke-width="2.4" '
              'stroke-linecap="round" stroke-linejoin="round"/><path d="M15 7.5h5v5" fill="none" stroke="{fg}" '
              'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'),
    "sliders": ('<g stroke="{fg}" stroke-width="2.2" stroke-linecap="round"><path d="M4 7h16M4 17h16"/></g>'
                '<circle cx="9" cy="7" r="2.8" fill="{fg}"/><circle cx="15.5" cy="17" r="2.8" fill="{fg}"/>'),
    "target": ('<circle cx="12" cy="12" r="8" fill="none" stroke="{fg}" stroke-width="2.2"/>'
               '<circle cx="12" cy="12" r="3.2" fill="{fg}"/>'),
    "code": ('<path d="M8.5 6.5 3 12l5.5 5.5M15.5 6.5 21 12l-5.5 5.5" fill="none" stroke="{fg}" '
             'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'),
}


def icon_tile(card: Card, x, y, name, size=44):
    s = size / 24 * 0.62
    off = (size - 24 * s) / 2
    return (f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{size * 0.27:.1f}" fill="{card.c["icon_bg"]}"/>'
            f'<g transform="translate({x + off:.2f} {y + off:.2f}) scale({s:.3f})">'
            f'{ICONS[name].format(fg=card.c["icon_fg"])}</g>')


# ── Data ─────────────────────────────────────────────────────────────────────
def sample_data() -> dict:
    rng = random.Random(27)
    end = date(2026, 11, 18)
    start = end - timedelta(days=364)
    start -= timedelta(days=(start.weekday() + 1) % 7)  # back to Sunday, like GitHub
    days, d = [], start
    while d <= end:
        season = 0.55 + 0.45 * math.sin((d.toordinal() % 365) / 365 * 2 * math.pi + 1.3)
        burst = 2.2 if d.month in (2, 10) else 1.0
        active = rng.random() < (0.28 + 0.35 * season) * (0.6 if d.weekday() >= 5 else 1)
        count = int(rng.expovariate(1 / (3.2 * season * burst)) + 1) if active else 0
        days.append({"date": d.isoformat(), "count": count})
        d += timedelta(days=1)
    for i in range(1, 13):  # a visible current streak
        days[-i]["count"] = max(days[-i]["count"], rng.randint(1, 6))
    repos = [
        {"name": "ather-obd-monitor", "description": "", "stars": 1, "forks": 0,
         "pushed_at": "2026-10-28T17:22:12Z", "language": "C++", "language_color": "#f34b7d",
         "url": "https://github.com/CoderHaste/ather-obd-monitor", "topics": []},
        {"name": "Customer-Churn-Prediction-ML", "description": "", "stars": 1, "forks": 0,
         "pushed_at": "2026-02-24T15:53:53Z", "language": "Python", "language_color": "#3572A5",
         "url": "https://github.com/CoderHaste/Customer-Churn-Prediction-ML", "topics": []},
        {"name": "Hyperparameter-Optimization-Optuna-vs-GridSearch", "description": "", "stars": 0,
         "forks": 0, "pushed_at": "2026-02-24T16:26:55Z", "language": "Python",
         "language_color": "#3572A5",
         "url": "https://github.com/CoderHaste/Hyperparameter-Optimization-Optuna-vs-GridSearch",
         "topics": []},
    ]
    return {
        "sample": True,
        "generated_at": "sample",
        "user": {"login": CONFIG["login"], "name": CONFIG["name"], "followers": 6,
                 "public_repos": 13, "stars": 6, "language_counts": {"Python": 8, "C++": 2}},
        "total_contributions": sum(x["count"] for x in days),
        "calendar": days,
        "repos": repos,
    }


def load_data() -> dict:
    p = ROOT / "data" / "github.json"
    if p.exists():
        return json.loads(p.read_text())
    print("data/github.json not found: rendering with SAMPLE data")
    return sample_data()


def stats(data: dict) -> dict:
    cal = sorted(data["calendar"], key=lambda x: x["date"])
    cal = [{"date": date.fromisoformat(x["date"]), "count": x["count"]} for x in cal]
    last = cal[-365:]
    active = sum(1 for x in last if x["count"] > 0)
    # longest streak
    longest = run = 0
    for x in cal:
        run = run + 1 if x["count"] else 0
        longest = max(longest, run)
    # current streak (today may still be empty)
    cur, i = 0, len(cal) - 1
    if i >= 0 and cal[i]["count"] == 0:
        i -= 1
    while i >= 0 and cal[i]["count"] > 0:
        cur += 1
        i -= 1
    busiest = max(last, key=lambda x: x["count"]) if last else {"date": date.today(), "count": 0}
    # monthly totals for the last 12 calendar months (including the current one)
    end = cal[-1]["date"]
    months = []
    y, m = end.year, end.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    totals = {k: 0 for k in months}
    for x in cal:
        k = (x["date"].year, x["date"].month)
        if k in totals:
            totals[k] += x["count"]
    return dict(cal=cal, active=active, window=len(last), longest=longest, current=cur,
                busiest=busiest, months=[(k, totals[k]) for k in months],
                total=sum(x["count"] for x in last))


def wrap(s: str, width: float, size: float, weight=500, max_lines=3) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if measure(t, size, weight) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while measure(lines[-1] + "…", size, weight) > width:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def fmt_month(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return f"{MONTHS[d.month - 1]} {d.year}"


# ── Cards ────────────────────────────────────────────────────────────────────
def card_hero(theme, data, st, base=0.0):
    W, H = 840, 260
    c = Card(W, H, theme, base, f"{CONFIG['name']}: {CONFIG['tagline']}")
    c.add(c.surface())
    # header strip, like the dashboard app bar
    c.add(f'<g{c.anim("rise", 0.0)}>' + icon_tile(c, 32, 30, "target", 40)
          + c.text(84, 47, f"@{CONFIG['login']}", 16, 800)
          + c.text(84, 64, f"Profile · {CONFIG['location']}", 12, 500, "muted") + "</g>")
    status = CONFIG.get("status", "")
    if status:
        sw = measure(status, 12, 700) + 38
        x0 = 556 - sw
        c.add(f'<g{c.anim("fade", 0.15)}><rect x="{x0}" y="36" width="{sw}" height="26" rx="13" '
              f'fill="{c.c["surface2"]}"/>' + c.live_dot(x0 + 15, 49, 3.5)
              + c.text(x0 + 25, 53.3, status, 12, 700, "accent") + "</g>")
    c.add(f'<line x1="32" y1="88" x2="556" y2="88" stroke="{c.c["line"]}"/>')
    # name + tagline
    c.add(f'<g{c.anim("rise", 0.15, 0.8)}>'
          + c.text(30, 150, CONFIG["name"], 46, 800, ls=-0.035) + "</g>")
    lines = wrap(CONFIG["tagline"], 520, 17, 500, 2)
    c.add(f'<g{c.anim("rise", 0.3, 0.8)}>'
          + "".join(c.text(32, 186 + i * 25, ln, 17, 500, "muted") for i, ln in enumerate(lines)) + "</g>")

    # right: the "focus" ring = share of days with contributions in the last year
    cx, cy, r = 704, 130, 82
    pct = 100 * st["active"] / max(st["window"], 1)
    circ = 2 * math.pi * r
    arc = circ * pct / 100
    c.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{c.c["track"]}" stroke-width="13"/>')
    kf = c.keyframe("ring", f"from{{stroke-dashoffset:{arc:.1f}}}to{{stroke-dashoffset:0}}")
    c.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{c.c["accent"]}" stroke-width="13" '
          f'stroke-linecap="round" stroke-dasharray="{arc:.1f} {circ:.1f}" '
          f'transform="rotate(-90 {cx} {cy})"{c.anim(kf, 0.35, 1.6)}/>')
    portrait = ROOT / CONFIG.get("portrait", "") if CONFIG.get("portrait") else None
    whole, frac = f"{pct:.2f}".split(".")
    if portrait and portrait.is_file():
        mime = "image/png" if portrait.suffix.lower() == ".png" else "image/jpeg"
        b64 = base64.b64encode(portrait.read_bytes()).decode()
        c.add(f'<clipPath id="pc"><circle cx="{cx}" cy="{cy}" r="{r - 16}"/></clipPath>'
              f'<image x="{cx - r + 16}" y="{cy - r + 16}" width="{2 * r - 32}" height="{2 * r - 32}" '
              f'preserveAspectRatio="xMidYMid slice" clip-path="url(#pc)" href="data:{mime};base64,{b64}"'
              f'{c.anim("fade", 0.3, 1.0)}/>')
        p, _ = c.pill(cx, cy + r - 6, f"{pct:.0f}% ACTIVE", "accent", "surface", 11, 9, 22, "middle")
        c.add(f'<g{c.anim("pop", 1.4, 0.5)} class="gc">{p}</g>')
    else:
        c.add(f'<g{c.anim("fade", 0.6, 0.8)}>'
              f'<text x="{cx}" y="{cy + 8}" text-anchor="middle" font-weight="800" fill="{c.c["text"]}" '
              f'letter-spacing="-1.4" font-size="44">{whole}<tspan font-size="20" fill="{c.c["muted"]}" '
              f'letter-spacing="0">.{frac}%</tspan></text>'
              + c.label(cx, cy + 30, "Days active", "middle", size=10)
              + c.text(cx, cy + 46, f"{st['active']} of {st['window']}", 11, 500, "muted", "middle")
              + "</g>")
        c.chars[800].update(whole + "." + frac + "%")
    c.add(c.sample_stamp(data, x=W - 18, y=H - 12) if data.get("sample") else "")
    return c.render()


def card_tile(theme, data, tile, base=0.0):
    W, H = 270, 158
    c = Card(W, H, theme, base, tile["label"], gap=0)
    u = data["user"]
    counts = u.get("language_counts", {})
    total = max(u.get("public_repos", 0), 1)
    if tile["languages"] == "*":
        n = u.get("public_repos", 0)
    else:
        n = sum(counts.get(lang, 0) for lang in tile["languages"])
    share = min(n / total, 1.0)
    c.add(c.surface())
    c.add(c.label(20, 32, tile["label"]))
    badge = "↗"
    p, _ = c.pill(W - 18, 15, f"{share * 100:.0f}%", "accent_soft", "accent", 11, 8, 22, "end")
    c.add(f'<g{c.anim("fade", 0.2)}>{p}</g>')
    c.add(f'<g{c.anim("rise", 0.05)}>' + c.value(19, 84, n, tile["unit"], 40) + "</g>")
    cap = tile["caption"].replace("{stars}", str(u.get("stars", 0)))
    c.add(f'<g{c.anim("fade", 0.25)}>' + c.text(20, 110, cap, 12.5, 500, "muted")
          + c.text(W - 20, 110, badge, 14, 700, "accent", "end") + "</g>")
    bw = W - 40
    c.add(f'<rect x="20" y="128" width="{bw}" height="6" rx="3" fill="{c.c["track"]}"/>')
    c.add(f'<rect class="gx" x="20" y="128" width="{max(bw * share, 6):.1f}" height="6" rx="3" '
          f'fill="{c.c["accent"]}"{c.anim("growx", 0.3, 1.1)}/>')
    if data.get("sample"):
        c.add(c.text(W - 20, 150, "sample", 9, 700, "warn", "end"))
    return c.render()


def card_activity(theme, data, st, base=0.0):
    W, H = 840, 340
    c = Card(W, H, theme, base, "Contributions per month")
    c.add(c.surface())
    c.add(c.label(32, 40, "Contributions · last 12 months"))
    c.add(f'<g{c.anim("rise", 0.0)}>' + c.value(30, 82, f"{st['total']:,}", "contributions", 34, unit_ratio=0.42) + "</g>")
    c.add(c.sample_stamp(data, y=34))
    months = st["months"]
    peak = max((v for _, v in months), default=1) or 1
    x0, x1, top, bottom = 32, W - 32, 112, 236
    slot = (x1 - x0) / len(months)
    bw = slot * 0.56
    for i in range(4):  # gridlines
        gy = bottom - (bottom - top) * i / 3
        dashed = ' stroke-dasharray="3 4"' if i else ""
        c.add(f'<line x1="{x0}" x2="{x1}" y1="{gy:.1f}" y2="{gy:.1f}" stroke="{c.c["line"]}"{dashed}/>')
    for i, ((yy, mm), v) in enumerate(months):
        h = max((bottom - top) * v / peak, 3 if v else 0)
        bx = x0 + slot * i + (slot - bw) / 2
        is_peak = v == peak and v > 0
        fill = c.c["accent"] if is_peak else c.c["accent2"]
        op = "1" if is_peak else ".45"
        if h:
            c.add(f'<rect class="gy" x="{bx:.1f}" y="{bottom - h:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                  f'rx="6" fill="{fill}" fill-opacity="{op}"{c.anim("grow", 0.2 + i * 0.06, 0.9)}/>')
        c.add(f'<g{c.anim("fade", 0.5 + i * 0.06, 0.5)}>'
              + c.text(bx + bw / 2, bottom - h - 8, v, 11, 800 if is_peak else 700,
                       "accent" if is_peak else "muted", "middle") + "</g>")
        c.add(c.text(bx + bw / 2, bottom + 20, MONTHS[mm - 1], 11, 700 if is_peak else 500,
                     "text" if is_peak else "muted", "middle"))
    # stat row, like RANGE / VOLTAGE / MODE
    row_y = 272
    c.add(f'<line x1="32" x2="{W - 32}" y1="{row_y}" y2="{row_y}" stroke="{c.c["line"]}"/>')
    b = st["busiest"]
    cells = [
        ("Current streak", st["current"], "day" if st["current"] == 1 else "days"),
        ("Longest streak", st["longest"], "day" if st["longest"] == 1 else "days"),
        ("Active days", st["active"], f"/ {st['window']}"),
        ("Busiest day", f"{MONTHS[b['date'].month - 1]} {b['date'].day}", f"· {b['count']}"),
    ]
    colw = (W - 64) / 4
    for i, (lab, num, unit) in enumerate(cells):
        cx = 32 + colw * i + colw / 2
        if i:
            c.add(f'<line x1="{32 + colw * i:.1f}" x2="{32 + colw * i:.1f}" y1="{row_y + 16}" y2="{H - 18}" '
                  f'stroke="{c.c["line"]}"/>')
        c.add(f'<g{c.anim("rise", 1.0 + i * 0.1)}>' + c.label(cx, row_y + 26, lab, "middle", size=10)
              + c.value(cx, row_y + 54, num, unit, 22, "middle", unit_ratio=0.55) + "</g>")
    return c.render()


def viz_pack(c: Card, x, y, w, h):
    """Nod to A-OBD's 'Pack balance · 14S' screen: 14 cell bars, one lagging."""
    out = [c.label(x + 16, y + 26, "Pack balance · 14S", size=10)]
    p, pw = c.pill(x + w - 14, y + 11, "CAN 500k", "accent_soft", "accent", 10, 8, 20, "end")
    out.append(p + c.live_dot(x + w - 14 - pw - 8, y + 21, 3))
    volts = [3.9123, 3.9140, 3.9101, 3.9155, 3.9132, 3.9098, 3.9040, 3.9144, 3.9150, 3.9120,
             3.9133, 3.9118, 3.9161, 3.8760]
    lo, hi = 3.86, 3.92
    n = len(volts)
    gx0, gx1, top, bottom = x + 16, x + w - 16, y + 46, y + h - 34
    slot = (gx1 - gx0) / n
    bw = slot * 0.62
    for i, v in enumerate(volts):
        hh = (bottom - top) * (v - lo) / (hi - lo)
        bx = gx0 + slot * i + (slot - bw) / 2
        warn = v == min(volts)
        out.append(f'<rect x="{bx:.1f}" y="{top}" width="{bw:.1f}" height="{bottom - top}" rx="{bw / 2:.1f}" '
                   f'fill="{c.c["track"]}"/>')
        out.append(f'<rect class="gy" x="{bx:.1f}" y="{bottom - hh:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                   f'rx="{bw / 2:.1f}" fill="{c.c["warn" if warn else "accent"]}"'
                   f'{c.anim("grow", 0.3 + i * 0.05, 0.9)}/>')
    out.append(f'<g{c.anim("fade", 1.1)}>'
               + c.text(x + 16, y + h - 12, "spread", 11, 500, "muted")
               + c.value(x + w - 16, y + h - 12, "0.0401", "v", 15, "end") + "</g>")
    return "".join(out)


def viz_roc(c: Card, x, y, w, h):
    out = [c.label(x + 16, y + 26, "ROC · 3 models", size=10)]
    px0, py0, pw, ph = x + 22, y + 42, w - 44, h - 74
    out.append(f'<rect x="{px0}" y="{py0}" width="{pw}" height="{ph}" fill="none" stroke="{c.c["line"]}"/>')
    out.append(f'<line x1="{px0}" y1="{py0 + ph}" x2="{px0 + pw}" y2="{py0}" stroke="{c.c["muted"]}" '
               f'stroke-opacity=".5" stroke-dasharray="3 4"/>')
    curves = [("RF", 3.0, "muted"), ("XGB", 3.8, "warn"), ("LGBM", 4.6, "accent")]
    for j, (name, k, col) in enumerate(curves):
        pts = []
        for i in range(41):
            t = i / 40
            fy = 1 - (1 - t) ** k
            pts.append(f"{px0 + pw * t:.1f},{py0 + ph * (1 - fy):.1f}")
        stroke = 2.6 if name == "LGBM" else 1.8
        dash = "" if STATIC else ' stroke-dasharray="1" stroke-dashoffset="0"'
        out.append(f'<path d="M{" L".join(pts)}" pathLength="1"{dash} fill="none" stroke="{c.c[col]}" '
                   f'stroke-width="{stroke}" stroke-linecap="round"{c.anim("draw", 0.35 + j * 0.25, 1.3)}/>')
    lx = x + 16
    for j, (name, _, col) in enumerate(curves):
        out.append(f'<g{c.anim("fade", 1.2 + j * 0.1)}><rect x="{lx}" y="{y + h - 21}" width="10" height="3" '
                   f'rx="1.5" fill="{c.c[col]}"/>' + c.text(lx + 15, y + h - 15.5, name, 10.5, 700, "muted") + "</g>")
        lx += 24 + measure(name, 10.5, 700)
    return "".join(out)


def viz_optuna(c: Card, x, y, w, h):
    out = [c.label(x + 16, y + 26, "Optuna · best so far", size=10)]
    rng = random.Random(7)
    px0, py0, pw, ph = x + 22, y + 42, w - 44, h - 74
    out.append(f'<line x1="{px0}" y1="{py0 + ph}" x2="{px0 + pw}" y2="{py0 + ph}" stroke="{c.c["line"]}"/>')
    n, best, pts, steps = 32, 0.0, [], []
    for i in range(n):
        explore = 1 - i / n
        s = min(0.97, 0.62 + 0.3 * (i / n) ** 0.5 + rng.uniform(-0.18, 0.06) * explore)
        pts.append(s)
        best = max(best, s)
        steps.append(best)
    lo, hi = 0.4, 1.0
    X = lambda i: px0 + pw * i / (n - 1)
    Y = lambda v: py0 + ph * (1 - (v - lo) / (hi - lo))
    for i, s in enumerate(pts):
        newbest = i == 0 or steps[i] > steps[i - 1]
        out.append(f'<circle class="gc" cx="{X(i):.1f}" cy="{Y(s):.1f}" r="{3.2 if newbest else 2.4}" '
                   f'fill="{c.c["accent" if newbest else "muted"]}" fill-opacity="{1 if newbest else .45}"'
                   f'{c.anim("pop", 0.3 + i * 0.03, 0.4)}/>')
    d = f"M{X(0):.1f},{Y(steps[0]):.1f}"
    for i in range(1, n):
        d += f" H{X(i):.1f} V{Y(steps[i]):.1f}"
    dash = "" if STATIC else ' stroke-dasharray="1" stroke-dashoffset="0"'
    out.append(f'<path d="{d}" pathLength="1"{dash} fill="none" stroke="{c.c["accent"]}" stroke-width="2.2" '
               f'stroke-linejoin="round"{c.anim("draw", 0.9, 1.4)}/>')
    out.append(f'<g{c.anim("fade", 1.6)}>' + c.text(x + 16, y + h - 12, f"{n} trials", 11, 500, "muted")
               + c.text(x + w - 16, y + h - 12, "TPE sampler", 11, 700, "accent", "end") + "</g>")
    return "".join(out)


def viz_generic(c: Card, x, y, w, h, repo):
    out = [c.label(x + 16, y + 26, "Repo", size=10)]
    out.append(f'<g{c.anim("rise", 0.3)}>' + c.value(x + w / 2, y + h / 2 + 8, repo.get("stars", 0), "★", 40, "middle")
               + c.text(x + w / 2, y + h / 2 + 34, f"{repo.get('forks', 0)} forks", 12, 500, "muted", "middle")
               + "</g>")
    return "".join(out)


def card_repo(theme, data, feat, base=0.0):
    W, H = 840, 236
    repo = next((r for r in data["repos"] if r["name"] == feat["repo"]), {"name": feat["repo"]})
    c = Card(W, H, theme, base, feat.get("title", repo["name"]))
    c.add(c.surface())
    panel_x, panel_w = W - 28 - 252, 252
    tx = 28
    c.add(f'<g{c.anim("rise", 0.0)}>' + icon_tile(c, tx, 28, feat.get("icon", "code"), 46)
          + c.text(tx + 60, 50, feat.get("title", repo["name"]), 22, 800, ls=-0.02))
    meta = []
    if repo.get("language"):
        meta.append(repo["language"])
    meta.append(f"★ {repo.get('stars', 0)}")
    if repo.get("pushed_at"):
        meta.append(f"updated {fmt_month(repo['pushed_at'])}")
    lang_col = repo.get("language_color") or c.c["muted"]
    c.add(f'<circle cx="{tx + 65}" cy="{65.5}" r="4" fill="{lang_col}"/>'
          + c.text(tx + 75, 70, "  ·  ".join(meta), 12.5, 500, "muted") + "</g>")
    blurb = feat.get("blurb") or repo.get("description") or ""
    lines = wrap(blurb, panel_x - tx - 28, 15, 500, 3)
    c.add(f'<g{c.anim("rise", 0.15)}>'
          + "".join(c.text(tx, 112 + i * 23, ln, 15, 500) for i, ln in enumerate(lines)) + "</g>")
    cx = tx
    tags = feat.get("tags") or repo.get("topics", [])[:4]
    for i, t in enumerate(tags):
        p, pw = c.pill(cx, H - 52, t, "surface2", "text", 12, 11, 26)
        if cx + pw > panel_x - 20:
            break
        c.add(f'<g{c.anim("rise", 0.3 + i * 0.07, 0.5)}>{p}</g>')
        cx += pw + 8
    # right panel with a per-project visual
    py, ph = 24, H - 48
    c.add(f'<rect x="{panel_x}" y="{py}" width="{panel_w}" height="{ph}" rx="16" fill="{c.c["surface2"]}"/>')
    viz = feat.get("viz")
    if viz == "pack":
        c.add(viz_pack(c, panel_x, py, panel_w, ph))
    elif viz == "roc":
        c.add(viz_roc(c, panel_x, py, panel_w, ph))
    elif viz == "optuna":
        c.add(viz_optuna(c, panel_x, py, panel_w, ph))
    else:
        c.add(viz_generic(c, panel_x, py, panel_w, ph, repo))
    return c.render()


def card_graph(theme, data, st, base=0.0):
    W, H = 840, 236
    c = Card(W, H, theme, base, "Contribution graph")
    c.add(c.surface())
    c.add(c.label(32, 40, "Contribution graph"))
    c.add(c.sample_stamp(data, y=34))
    cal = st["cal"][-371:]
    # align first column to Sunday
    first = cal[0]["date"]
    lead = (first.weekday() + 1) % 7
    cells = [None] * lead + cal
    nonzero = sorted(x["count"] for x in cal if x["count"])
    q = [nonzero[int(len(nonzero) * f)] for f in (0.25, 0.5, 0.75)] if nonzero else [1, 2, 3]

    def level(n):
        if n == 0:
            return 0
        return 1 + sum(n > t for t in q)

    size, gap = 11, 3
    step = size + gap
    weeks = math.ceil(len(cells) / 7)
    gx = W - 32 - weeks * step + gap
    gy = 80
    last_month = None
    for wi in range(weeks):
        col = cells[wi * 7: wi * 7 + 7]
        firstday = next((d for d in col if d), None)
        if firstday and firstday["date"].month != last_month and firstday["date"].day <= 7:
            c.add(c.text(gx + wi * step, gy - 10, MONTHS[firstday["date"].month - 1], 10, 500, "muted"))
            last_month = firstday["date"].month
        for di, d in enumerate(col):
            if not d:
                continue
            lv = level(d["count"])
            c.add(f'<rect class="gc" x="{gx + wi * step}" y="{gy + di * step}" width="{size}" height="{size}" '
                  f'rx="2.5" fill="{c.c["heat"][lv]}"{c.anim("pop", 0.1 + wi * 0.018 + di * 0.01, 0.45)}/>')
    for di, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        c.add(c.text(gx - 8, gy + di * step + 9, name, 10, 500, "muted", "end"))
    # today marker
    if not STATIC and cal:
        lastcell = len(cells) - 1
        wi, di = divmod(lastcell, 7)
        x, y = gx + wi * step, gy + di * step
        c.add(f'<rect class="loop" x="{x - 2}" y="{y - 2}" width="{size + 4}" height="{size + 4}" rx="4" fill="none" '
              f'stroke="{c.c["accent"]}" stroke-width="1.5"><animate attributeName="stroke-opacity" '
              f'values="1;.15;1" dur="2s" repeatCount="indefinite"/></rect>')
    # legend
    ly = H - 30
    c.add(c.text(32, ly + 9, f"{st['total']:,} contributions in the last year", 12, 500, "muted"))
    lx = W - 32 - 5 * step - measure("More", 10, 500) - 8
    c.add(c.text(lx - 8, ly + 9, "Less", 10, 500, "muted", "end"))
    for i in range(5):
        c.add(f'<rect x="{lx + i * step}" y="{ly}" width="{size}" height="{size}" rx="2.5" fill="{c.c["heat"][i]}"/>')
    c.add(c.text(lx + 5 * step + 5, ly + 9, "More", 10, 500, "muted"))
    return c.render()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    data = load_data()
    st = stats(data)
    written = []
    for theme in THEMES:
        d = OUT / theme
        d.mkdir(parents=True, exist_ok=True)
        files = {"hero.svg": card_hero(theme, data, st, 0.0)}
        for i, tile in enumerate(CONFIG["tiles"]):
            files[f"tile-{tile['id']}.svg"] = card_tile(theme, data, tile, 0.45 + i * 0.15)
        files["activity.svg"] = card_activity(theme, data, st, 1.0)
        for i, feat in enumerate(CONFIG["featured"]):
            files[f"repo-{feat['repo']}.svg"] = card_repo(theme, data, feat, 1.8 + i * 0.45)
        files["graph.svg"] = card_graph(theme, data, st, 1.8 + len(CONFIG["featured"]) * 0.45 + 0.2)
        for name, svg in files.items():
            (d / name).write_text(svg)
            written.append((f"{theme}/{name}", len(svg)))
    mode = "STATIC (final frame)" if STATIC else "animated"
    print(f"Rendered {len(written)} cards, {mode}{', SAMPLE data' if data.get('sample') else ''}:")
    for n, size in written:
        print(f"  cards/{n:<58} {size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
