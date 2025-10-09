import re
from typing import List, Tuple, Optional

from bs4 import BeautifulSoup  # type: ignore

ALLOWED_TAGS = {"p", "ul", "ol", "li", "em", "strong", "br", "a", "h2", "h3"}


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        elif tag.name == "a":
            # keep only href
            attrs = {k: v for k, v in tag.attrs.items() if k == "href"}
            tag.attrs = attrs
        else:
            tag.attrs = {}
    return str(soup)


def normalize_text(text: str) -> str:
    # Fix common UTF-8 artifacts like â€¢ becoming •
    text = text.replace("â€¢", "•")
    text = re.sub(r"\s+", " ", text).strip()
    return text


_TECH_DICT = {
    "typescript": "TypeScript",
    "react": "React",
    "node": "Node.js",
    "python": "Python",
    "java": "Java",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "kubernetes": "Kubernetes",
}


def extract_tech_stack(text: str) -> List[str]:
    lowered = text.lower()
    found = []
    for k, v in _TECH_DICT.items():
        if k in lowered:
            found.append(v)
    return sorted(set(found))


def normalize_salary(raw: str) -> Tuple[float, float, str, str]:
    # Very simple regex-based extractor; to be improved.
    # Returns (min, max, currency, periodicity)
    m = re.search(r"\$\s*([0-9][0-9,]*)\s*-\s*\$\s*([0-9][0-9,]*)", raw)
    if m:
        mn = float(m.group(1).replace(",", ""))
        mx = float(m.group(2).replace(",", ""))
        return (mn, mx, "USD", "year")
    return (0.0, 0.0, "", "")


def guess_location(text: str) -> str:
    if "remote" in text.lower():
        return "Remote"
    return "Unknown"


# -------- Salary and location normalization v2 (non-breaking helpers) --------

_CURRENCY_MAP = {
    "$": "USD",
    "£": "GBP",
    "€": "EUR",
}


def parse_salary_components(text: str) -> Optional[Tuple[float, float, str, str, str]]:
    """
    Try to extract (min, max, currency, periodicity, raw) from free text.
    Supports formats like "$140k–$180k", "$140,000 - $180,000", "€70,000 per year", "£80k-£100k".
    Periodicity heuristics: year|annual|yr, month|mo, hour|hr.
    Returns None if not found.
    """
    if not text:
        return None
    t = text.lower().replace("\u2013", "-").replace("\u2014", "-")  # normalize dashes
    # currency symbol
    cur_sym = None
    for sym in _CURRENCY_MAP:
        if sym in text:
            cur_sym = sym
            break
    currency = _CURRENCY_MAP.get(cur_sym or "", "")

    # Extract numbers with optional k and thousands separators
    # Examples: 140k - 180k, 140,000 - 180,000, 70k
    m = re.search(r"(\d+[\d,]*\s*(k)?)\s*[-to–]+\s*(\d+[\d,]*\s*(k)?)", t)
    single = re.search(r"(\d+[\d,]*\s*(k)?)", t) if not m else None

    mn = mx = None
    if m:
        g1, k1, g2, k2 = m.group(1), m.group(2), m.group(3), m.group(4)
        def to_num(g, kflag):
            val = float(g.replace(",", "").replace(" ", ""))
            if kflag:
                val *= 1000.0
            return val
        # remove trailing k letters in numeric conversion
        def clean_num(s: str) -> Tuple[float, bool]:
            kflag = s.strip().endswith("k")
            s2 = s.strip().rstrip("k").replace(",", "")
            return (float(s2), kflag)
        v1_raw, v2_raw = g1, g2
        v1, kf1 = clean_num(v1_raw)
        v2, kf2 = clean_num(v2_raw)
        if kf1:
            v1 *= 1000.0
        if kf2:
            v2 *= 1000.0
        mn, mx = v1, v2
    elif single:
        g1 = single.group(1)
        s_clean = g1.strip().rstrip("k").replace(",", "")
        try:
            val = float(s_clean)
            if g1.strip().endswith("k"):
                val *= 1000.0
            mn = mx = val
        except Exception:
            return None
    else:
        return None

    # periodicity
    period = "year"
    if any(p in t for p in ["per month", "/mo", "monthly", "per mo"]):
        period = "month"
    elif any(p in t for p in ["per hour", "/hr", "hourly", "per hr"]):
        period = "hour"
    elif any(p in t for p in ["per year", "/yr", "yearly", "annual", "annually"]):
        period = "year"

    raw = text.strip()
    return (float(mn), float(mx), currency, period, raw)


def refine_location(text: str, fallback: str = "Unknown") -> str:
    """Improve location guess with common patterns like Remote, Hybrid, EU Remote, US/CA, etc."""
    if not text:
        return fallback
    tl = text.lower()
    if "hybrid" in tl:
        return "Hybrid"
    if "remote" in tl:
        if "eu" in tl:
            return "EU Remote"
        if "us" in tl or "usa" in tl or "united states" in tl:
            return "US Remote"
        if "ca" in tl or "canada" in tl:
            return "CA Remote"
        return "Remote"
    # simple city/country hints
    if "san francisco" in tl:
        return "San Francisco, CA"
    if "new york" in tl:
        return "New York, NY"
    if "london" in tl:
        return "London, UK"
    if "berlin" in tl:
        return "Berlin, DE"
    return fallback


# -------- List extraction and section classification --------

_RESP_KEYS = [
    "responsibilities",
    "what you'll do",
    "what you will do",
    "duties",
    "role",
    "what you do",
]

_REQ_KEYS = [
    "requirements",
    "qualifications",
    "what we're looking for",
    "what we are looking for",
    "you have",
    "must have",
    "nice to have",
]

_BEN_KEYS = [
    "benefits",
    "perks",
    "compensation and benefits",
]


def classify_section(heading: str) -> str | None:
    h = (heading or "").strip().lower()
    if not h:
        return None
    if any(k in h for k in _RESP_KEYS):
        return "responsibilities"
    if any(k in h for k in _REQ_KEYS):
        return "requirements"
    if any(k in h for k in _BEN_KEYS):
        return "benefits"
    return None


def extract_list_items_from_html(html: str) -> list[str]:
    items: list[str] = []
    soup = BeautifulSoup(html or "", "html.parser")
    for li in soup.select("li"):
        t = normalize_text(li.get_text(" "))
        if t:
            items.append(t)
    # de-dup while preserving order
    seen = set()
    out: list[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out
