"""Value helpers shared by every Yelp parser: links, photos, dates, cursors,
pagination. Pure functions, no network; every helper tolerates None and junk.

num / to_int / text / iso_date are the same four generic helpers as
similarweb/shared.py, kept here so the yelp package stands alone (it ships
as a self-contained open-source module that cannot import another site)."""
import base64
import html as html_lib
import json
import math
import re
from datetime import datetime, timezone

SITE = "https://www.yelp.com"


def num(value):
    """int / float / numeric string -> float; bool, junk, NaN -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    try:
        out = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return out if out == out else None


def to_int(value):
    out = num(value)
    return int(round(out)) if out is not None else None


def text(value):
    """Whitespace-collapsed, HTML-unescaped string; '' -> None."""
    if value is None:
        return None
    out = " ".join(html_lib.unescape(str(value)).replace("\xa0", " ").split())
    return out or None


def iso_date(value):
    """'2026-08-01T00:00:00+00:00' / '2026-08-01' -> '2026-08-01'."""
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if not match or match.group(1) == "0001":
        return None
    return "-".join(match.groups())
_PHOTO_RE = re.compile(r"https?://[^/]+\.yelpcdn\.com/(bphoto|photo|buphoto|projectphoto|ephoto|mphoto)/([^/]+)/[^/?#]+")


def dig(obj, *path, default=None):
    """obj[path0][path1]... with None on any missing / wrong-typed step."""
    for key in path:
        if isinstance(key, int):
            if not isinstance(obj, list) or not -len(obj) <= key < len(obj):
                return default
            obj = obj[key]
        elif isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return default
        if obj is None:
            return default
    return obj


def as_list(value):
    return value if isinstance(value, list) else []


def edges(connection):
    """[node, ...] of a GraphQL connection (edges[].node), None nodes dropped."""
    return [e.get("node") for e in as_list(dig(connection, "edges")) if isinstance(e, dict) and e.get("node")]


# ---- text --------------------------------------------------------------------------

def paragraphs(value):
    """Review / bio text: HTML-unescaped, line breaks kept, '' -> None."""
    if value is None:
        return None
    out = html_lib.unescape(str(value)).replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    out = re.sub(r"<br\s*/?>", "\n", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out or None


def strip_tags(value):
    """'<b>Outdoor seating</b>' -> 'Outdoor seating'."""
    if value is None:
        return None
    return text(re.sub(r"<[^>]+>", " ", str(value)))


def highlight_text(value):
    """Yelp's '[[HIGHLIGHT]]pizza[[ENDHIGHLIGHT]]' markers -> plain text."""
    if value is None:
        return None
    return text(str(value).replace("[[HIGHLIGHT]]", "").replace("[[ENDHIGHLIGHT]]", ""))


# ---- dates ---------------------------------------------------------------------------

def utc_datetime(value):
    """'2026-08-17T15:17:33-07:00' / '2022-10-16T01:35:42Z' / '…00.000Z' ->
    '2026-08-17T22:17:33Z' (UTC). A naive value is taken as UTC."""
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    raw = re.sub(r"\.\d+(?=[+-]\d\d:\d\d$|$)", "", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_date(value):
    """The calendar date as written ('2026-08-17T15:17:33-07:00' -> '2026-08-17')."""
    return iso_date(value)


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def us_date(value):
    """'Jun 7, 2024' / '6/7/2024' -> '2024-06-07'."""
    if not value:
        return None
    s = str(value).strip()
    m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})", s)
    if m and m.group(1).lower() in _MONTHS:
        return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return iso_date(s)


def elite_year(value):
    """currentTruncatedEliteYear '26' -> 2026."""
    n = to_int(value)
    if n is None:
        return None
    return n + 2000 if n < 100 else n


# ---- links / photos ---------------------------------------------------------------------

def absolute(link):
    if not link:
        return None
    link = html_lib.unescape(str(link))
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return SITE + link
    return link


def biz_link(alias_or_id):
    return f"{SITE}/biz/{alias_or_id}" if alias_or_id else None


def user_link(encid):
    return f"{SITE}/user_details?userid={encid}" if encid else None


def photo_id(url):
    m = _PHOTO_RE.match(str(url or ""))
    return m.group(2) if m else None


def photo_link(url, size="o"):
    """Any Yelp CDN photo size (60s.jpg, 348s.jpg, l.jpg, ...) -> the same
    photo at `size` ('o' = the original upload). Other URLs pass through."""
    if not url:
        return None
    url = absolute(url)
    m = _PHOTO_RE.match(url)
    if not m:
        return url
    return url[:m.end()].rsplit("/", 1)[0] + f"/{size}.jpg"


def photo(encid=None, url=None, caption=None, width=None, height=None, uploaded_at=None, **extra):
    """The shared photo object: original + 348px thumbnail."""
    if not url and not encid:
        return None
    out = {"id": encid or photo_id(url), "link": photo_link(url, "o"), "thumbnail_link": photo_link(url, "348s"),
           "caption": text(caption), "width": to_int(width), "height": to_int(height),
           "uploaded_at": utc_datetime(uploaded_at)}
    out.update(extra)
    return out


# ---- money / price ----------------------------------------------------------------------

def price_level(display):
    """'$$$' -> 3 (also '€€', '£££', '¥¥'); None when not a run of one symbol."""
    s = (display or "").strip()
    if s and len(set(s)) == 1 and len(s) <= 4:
        return len(s)
    return None


_CURRENCY_BY_SYMBOL = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR", "₩": "KRW"}


def money(value, currency=None):
    """'$16.25' / '16.25' -> (16.25, 'USD')."""
    if value is None:
        return None, currency
    s = str(value).strip()
    cur = currency
    for sym, code in _CURRENCY_BY_SYMBOL.items():
        if s.startswith(sym) or s.endswith(sym):
            cur = cur or code
            break
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    return (num(m.group(0)) if m else None), cur


# ---- pagination / cursors ------------------------------------------------------------------

def offset_cursor(offset, string_version=False):
    """Yelp's GraphQL connection cursor for 'items after position `offset`'
    (base64 JSON; `after` = cursor(n) returns items n+1, n+2, ...)."""
    if offset is None or offset < 0:
        return None
    payload = ({"version": "1", "type": "offset", "offset": offset} if string_version
               else {"version": 1, "type": "offset", "offset": offset})
    raw = json.dumps(payload) if string_version else json.dumps(payload, separators=(",", ":"))
    return base64.b64encode(raw.encode()).decode().rstrip("=")


def page_after(page, page_size, string_version=False):
    """`after` cursor for a 1-based page of `page_size` items (None = page 1)."""
    if page <= 1:
        return None
    return offset_cursor((page - 1) * page_size - 1, string_version=string_version)


def pagination(page, page_size, total):
    total = to_int(total)
    return {"page": page, "items_per_page": page_size,
            "total_pages": math.ceil(total / page_size) if total else (0 if total == 0 else None),
            "total_count": total}
