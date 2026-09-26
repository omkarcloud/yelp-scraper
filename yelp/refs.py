"""Yelp reference parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrLinkField convention — never a sibling `url` / `id`
pair). Parsing is offline; the network step (alias -> encrypted id) lives
in businesses.resolve_business.

  business   gary-danko-san-francisco                      (alias, the /biz/ slug)
             WavvLdfdP6g8aZTtbBQHTw                        (22-char encrypted id)
             https://www.yelp.com/biz/gary-danko-san-francisco?osq=…
             any yelp.* / m.yelp.* host, and /biz_photos/, /menu/,
             /not_recommended_reviews/, /questions/, /writeareview/biz/ links
  user       CHV3OXUzMbMDZ5A07UGO5A | https://www.yelp.com/user_details?userid=…
             (any /user_details*?userid= or /user_local_photos?userid= link)
  question   2YQo0SgATXjcHt1sI-_taQ | https://www.yelp.com/questions/<biz>/<question>
  event      san-francisco-oktoberfest-2 | https://www.yelp.com/events/<slug>
  category   italian | Italian | a /search?…cflt=italian link   (categories.json)
  city       sf | san-francisco | a /events/<city> link          (event pages)
"""
import json
import os
import re
from functools import lru_cache
from urllib.parse import parse_qs, unquote, urlparse

YELP_HOST_RE = re.compile(r"(^|\.)yelp\.[a-z.]+$")
ENCID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
ALIAS_RE = re.compile(r"^[\w\-.'%~]{2,250}$", re.UNICODE)
SLUG_RE = re.compile(r"^[\w\-%.]{2,250}$", re.UNICODE)
_BIZ_PATH_RE = re.compile(r"^/(?:biz|biz_photos|menu|not_recommended_reviews|questions|writeareview/biz|map)/([^/?#]+)")


def _is_link(value):
    return value.startswith(("http://", "https://", "//", "www.", "yelp.", "m.yelp."))


def _parse_link(value, what):
    url = value if value.startswith(("http://", "https://")) else "https://" + value.lstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not YELP_HOST_RE.search(host):
        raise ValueError(f"not a Yelp link — pass a {what} or a yelp.com link")
    return parsed


def looks_like_encid(value):
    """22-char encrypted ids mix upper/lower case; aliases are lower-case
    words joined by '-' (a lower-case 22-char id is possible but rare, and
    resolve_business falls back to the alias lookup anyway)."""
    return bool(ENCID_RE.match(value)) and (any(c.isupper() for c in value) or "_" in value)


def business_ref(value):
    value = (value or "").strip()
    if _is_link(value):
        parsed = _parse_link(value, "business alias or id")
        m = _BIZ_PATH_RE.match(parsed.path)
        if not m:
            biz = parse_qs(parsed.query).get("biz_id") or parse_qs(parsed.query).get("bizid")
            if biz:
                return biz[0]
            raise ValueError("not a Yelp business link (expected https://www.yelp.com/biz/<alias>)")
        value = m.group(1)
    value = unquote(value).strip()
    if not ALIAS_RE.match(value):
        raise ValueError("must be a Yelp business alias (gary-danko-san-francisco), its 22-char id or its yelp.com link")
    return value


def business_refs(value, max_items=20):
    items = []
    for raw in re.split(r"[,\s]+", (value or "").strip()):
        if raw:
            ref = business_ref(raw)
            if ref not in items:
                items.append(ref)
    if not items:
        raise ValueError("pass at least one business alias, id or link")
    if len(items) > max_items:
        raise ValueError(f"at most {max_items} businesses per call")
    return items


def user_ref(value):
    value = (value or "").strip()
    if _is_link(value):
        parsed = _parse_link(value, "user id")
        ids = parse_qs(parsed.query).get("userid") or parse_qs(parsed.query).get("user_id")
        if not ids:
            raise ValueError("not a Yelp profile link (expected https://www.yelp.com/user_details?userid=<id>)")
        value = ids[0]
    if not ENCID_RE.match(value):
        raise ValueError("must be a Yelp user id (22 characters, e.g. CHV3OXUzMbMDZ5A07UGO5A) or a profile link")
    return value


def question_ref(value):
    value = (value or "").strip()
    if _is_link(value):
        parsed = _parse_link(value, "question id")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 3 or parts[0] != "questions":
            raise ValueError("not a Yelp question link (expected https://www.yelp.com/questions/<business>/<question>)")
        value = parts[2]
    if not ENCID_RE.match(value):
        raise ValueError("must be a Yelp question id (22 characters) or a question link")
    return value


def event_ref(value):
    value = (value or "").strip()
    if _is_link(value):
        parsed = _parse_link(value, "event slug")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) != 2 or parts[0] != "events":
            raise ValueError("not a Yelp event link (expected https://www.yelp.com/events/<slug>)")
        value = parts[1]
    value = unquote(value)
    if not SLUG_RE.match(value) or "-" not in value:
        raise ValueError("must be a Yelp event slug (san-francisco-some-event) or its link")
    return value


def event_city(value):
    value = (value or "").strip()
    if _is_link(value):
        parsed = _parse_link(value, "events city")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2 or parts[0] != "events":
            raise ValueError("not a Yelp events link (expected https://www.yelp.com/events/<city>)")
        value = parts[1]
    value = value.lower().replace(" ", "-")
    if not re.match(r"^[a-z0-9-]{2,60}$", value):
        raise ValueError("must be a Yelp events city slug (sf, la, nyc, chicago, ...) or an events link")
    return value


# ---- categories ------------------------------------------------------------------------

@lru_cache(maxsize=1)
def categories():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "categories.json")) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _category_index():
    index = {}
    for row in categories():
        index.setdefault(row["alias"].lower(), row["alias"])
        index.setdefault(row["title"].lower(), row["alias"])
    return index


def category_alias(value):
    value = (value or "").strip()
    if _is_link(value):
        parsed = _parse_link(value, "category")
        cflt = parse_qs(parsed.query).get("cflt")
        if not cflt:
            raise ValueError("not a Yelp category link (expected a search link with cflt=<alias>)")
        value = cflt[0]
    alias = _category_index().get(value.lower())
    if alias is None:
        raise ValueError(f"unknown Yelp category {value!r} — see /yelp/categories for the aliases")
    return alias
