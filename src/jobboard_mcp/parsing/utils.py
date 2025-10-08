import re
from typing import List, Tuple

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
