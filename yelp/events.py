"""/yelp/events/* — Yelp Events (legacy server-rendered pages, open over
plain curl): a city's event listings (15 per page, `start` offset) and one
event's details."""
from urllib.parse import urlencode

from yelp import fetch, parsers
from yelp.shared import pagination

EVENTS_PAGE_SIZE = 15
CATEGORIES = {"music": 1, "visual_arts": 2, "performing_arts": 3, "film": 4, "lectures_and_books": 5, "fashion": 6,
              "food_and_drink": 7, "festivals_and_fairs": 8, "charities": 9, "sports_and_active_life": 10,
              "nightlife": 11, "kids_and_family": 12, "other": 0}
SORTS = {"popular": None, "recently_added": "added", "free": "free"}


def search(city, category, sort_by, start_date, end_date, official_only, page):
    params = {}
    if category is not None:
        params["c"] = CATEGORIES[category]
    if official_only:
        params["official"] = 1
    if SORTS.get(sort_by or "popular"):
        params["sort_by"] = SORTS[sort_by]
    if start_date:
        params["start_date"] = start_date.replace("-", "")
    if end_date:
        params["end_date"] = end_date.replace("-", "")
    if page > 1:
        params["start"] = (page - 1) * EVENTS_PAGE_SIZE
    path = f"/events/{city}/browse" + (f"?{urlencode(params)}" if params else "")
    items = parsers.events_list(fetch.open_get(path))
    # The page shows no total; there is a next page while a page is full.
    total_pages = page + 1 if len(items) >= EVENTS_PAGE_SIZE else page
    out = pagination(page, EVENTS_PAGE_SIZE, None)
    out["total_pages"] = total_pages
    return {"city": city, "events": items, "pagination": out}


def details(event):
    return parsers.event_details(fetch.open_get(f"/events/{event}"), event)
