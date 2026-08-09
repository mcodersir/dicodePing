from __future__ import annotations

import base64
import html
import json
import re
import urllib.parse
from typing import Iterable

_UNKNOWN = {"", "unknown", "unnamed", "n/a", "none", "null", "نامشخص", "بدون نام", "ناشناخته"}
_GENERATED = re.compile(r"^(?:سرور|server)\s+.+?[•\-]\s*\d+$", re.I)
_BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_COUNTRIES = {"DE":"Germany","NL":"Netherlands","FR":"France","US":"United States","CA":"Canada","GB":"United Kingdom","TR":"Turkey","FI":"Finland","SE":"Sweden","NO":"Norway","SG":"Singapore","JP":"Japan","KR":"South Korea","HK":"Hong Kong","AE":"United Arab Emirates","IN":"India","IT":"Italy","ES":"Spain","AT":"Austria","CH":"Switzerland","PL":"Poland","RO":"Romania","RU":"Russia","AU":"Australia","BR":"Brazil"}
_KEYWORDS = {"germany":"DE","آلمان":"DE","netherlands":"NL","holland":"NL","هلند":"NL","france":"FR","فرانسه":"FR","united states":"US","usa":"US","america":"US","آمریکا":"US","canada":"CA","کانادا":"CA","united kingdom":"GB","england":"GB","انگلیس":"GB","turkey":"TR","ترکیه":"TR","finland":"FI","فنلاند":"FI","sweden":"SE","سوئد":"SE","norway":"NO","نروژ":"NO","singapore":"SG","سنگاپور":"SG","japan":"JP","ژاپن":"JP","korea":"KR","کره":"KR","hong kong":"HK","هنگ کنگ":"HK","uae":"AE","dubai":"AE","امارات":"AE","india":"IN","هند":"IN","italy":"IT","ایتالیا":"IT","spain":"ES","اسپانیا":"ES","austria":"AT","اتریش":"AT","switzerland":"CH","سوئیس":"CH","poland":"PL","لهستان":"PL","romania":"RO","رومانی":"RO","russia":"RU","روسیه":"RU","australia":"AU","استرالیا":"AU","brazil":"BR","برزیل":"BR"}


def clean_display_name(value: str | None) -> str:
    text = urllib.parse.unquote(html.unescape(str(value or "")))
    text = _BIDI.sub("", text)
    text = " ".join(text.split()).strip(" -_|•")
    return "" if text.casefold() in _UNKNOWN else text


def extract_display_name(raw: str) -> str:
    value = str(raw or "").strip()
    decoded = urllib.parse.unquote(html.unescape(value))
    if "#" in decoded:
        fragment = clean_display_name(decoded.rsplit("#", 1)[1])
        if fragment:
            return fragment
    if value.lower().startswith("vmess://"):
        try:
            data = value[8:].replace("-", "+").replace("_", "/")
            data += "=" * ((4 - len(data) % 4) % 4)
            obj = json.loads(base64.b64decode(data).decode("utf-8", "ignore"))
            for key in ("ps", "name", "remarks", "remark"):
                name = clean_display_name(obj.get(key))
                if name:
                    return name
        except Exception:
            return ""
    try:
        return clean_display_name(urllib.parse.urlsplit(decoded).fragment)
    except Exception:
        return clean_display_name(value.rsplit("#", 1)[1] if "#" in value else "")


def is_generated_or_unknown_name(value: str | None) -> bool:
    text = clean_display_name(value)
    return not text or bool(_GENERATED.match(text))


def infer_country_hint(name: str | None) -> tuple[str, str]:
    text = clean_display_name(name)
    flags = [ch for ch in text if 0x1F1E6 <= ord(ch) <= 0x1F1FF]
    code = ""
    if len(flags) >= 2:
        code = "".join(chr(ord(ch) - 0x1F1E6 + 65) for ch in flags[:2])
    if code not in _COUNTRIES:
        folded = text.casefold()
        code = next((v for k, v in _KEYWORDS.items() if k.casefold() in folded), "")
    return (code, _COUNTRIES.get(code, "")) if code else ("", "")


def choose_conservative_latency(values: Iterable[int | float | None]) -> int | None:
    samples = [int(round(float(v))) for v in values if v is not None and float(v) > 0]
    return max(samples) if samples else None
