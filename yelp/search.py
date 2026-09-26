"""/yelp/search*, /yelp/locations/autocomplete, /yelp/categories.

Search is /search/snippet (the JSON the search page loads; DataDome-gated,
fetch.gated_get) for the ranking, snippets, highlights and badges — its
organic results carry only business ids, the site hydrates names, ratings,
addresses from /gql/batch, and so do we (businesses.cards). Yelp serves 10
results per page and at most 240 per query (24 pages)."""
import json
from urllib.parse import urlencode

from yelp import businesses, fetch, parsers, refs
from yelp.shared import SITE, dig, pagination, text

SEARCH_PAGE_SIZE = 10
MAX_SEARCH_RESULTS = 240
SORTS = {"recommended": "recommended", "highest_rated": "rating", "most_reviewed": "review_count"}

# Public feature names -> Yelp's search `attrs` tokens (filterInfoMap of the
# search page, 2026-09-26). Raw Yelp tokens (from /yelp/search/filters) are
# accepted too, see schemas.FeaturesField.
FEATURES = {
    "open_now": "open_now", "offers_delivery": "RestaurantsDelivery", "offers_takeout": "RestaurantsTakeOut",
    "takes_reservations": "RestaurantsReservations", "online_reservations": "OnlineReservations",
    "online_waitlist": "OnlineWaitlistReservation", "good_for_breakfast": "GoodForMeal.breakfast",
    "good_for_brunch": "GoodForMeal.brunch", "good_for_lunch": "GoodForMeal.lunch", "good_for_dinner": "GoodForMeal.dinner",
    "good_for_dessert": "GoodForMeal.dessert", "good_for_late_night": "GoodForMeal.latenight",
    "vegetarian": "vegetarian", "vegan": "vegan", "halal": "halal", "kosher": "kosher",
    "hot_and_new": "hottest_new_opening", "outdoor_seating": "OutdoorSeating", "good_for_kids": "GoodForKids",
    "good_for_groups": "RestaurantsGoodForGroups", "dogs_allowed": "DogsAllowed", "full_bar": "Alcohol.full_bar",
    "beer_and_wine": "Alcohol.beer_and_wine", "happy_hour": "HappyHour", "free_wifi": "WiFi.free", "paid_wifi": "WiFi.paid",
    "has_tv": "HasTV", "wheelchair_accessible": "WheelchairAccessible", "gender_neutral_restrooms": "GenderNeutralRestrooms",
    "accepts_credit_cards": "BusinessAcceptsCreditCards", "accepts_apple_pay": "BusinessAcceptsApplePay",
    "accepts_cryptocurrency": "BusinessAcceptsBitcoin", "military_discount": "OffersMilitaryDiscount",
    "open_to_all": "BusinessOpenToAll", "by_appointment_only": "ByAppointmentOnly", "open_24_hours": "Open24Hours",
    "waiter_service": "RestaurantsTableService", "coat_check": "CoatCheck", "free_delivery": "FreeDelivery",
    "fast_delivery": "FastDelivery", "low_delivery_fee": "CheapDelivery", "flower_delivery": "FlowerDelivery",
    "online_booking": "PlatformOnlineBooking", "online_appointments": "PlatformSpaBooking",
    "service_booking": "offers_booking_task", "request_a_quote": "OnlineMessageThisBusiness",
    "virtual_consultations": "offers_virtual_consultations", "fast_responding": "is_fast_mtb_responder",
    "yelp_guaranteed": "is_yelp_guaranteed", "live_music": "Music.live", "dj": "Music.dj", "karaoke": "Music.karaoke",
    "jukebox": "Music.jukebox", "street_parking": "BusinessParking.street", "garage_parking": "BusinessParking.garage",
    "valet_parking": "BusinessParking.valet", "private_lot_parking": "BusinessParking.lot",
    "validated_parking": "BusinessParking.validated", "smoking_allowed": "Smoking.yes", "smoking_outdoor_only": "Smoking.outdoor",
    "no_smoking": "Smoking.no", "liked_by_vegetarians": "LikedByVegetarians", "liked_by_20_somethings": "LikedByTwenties",
    "liked_by_30_somethings": "LikedByThirties", "liked_by_40_somethings": "LikedByForties",
}


def _snippet_path(query, location, category, sort_by, price, features, page):
    params = {"find_desc": query or "", "find_loc": location}
    if category:
        params["cflt"] = category
    if sort_by and sort_by != "recommended":
        params["sortby"] = SORTS[sort_by]
    attrs = [f"RestaurantsPriceRange2.{p}" for p in sorted(price or [])] + list(features or [])
    if attrs:
        params["attrs"] = ",".join(attrs)
    if page > 1:
        params["start"] = (page - 1) * SEARCH_PAGE_SIZE
    qs = urlencode(params)
    return f"/search/snippet?{qs}", f"{SITE}/search?{qs}"


def search(query, location, category, sort_by, price, features, page):
    path, page_url = _snippet_path(query, location, category, sort_by, price, features, page)
    raw = json.loads(fetch.gated_get(path, accept="json", referer=page_url))
    organic, sponsored, ctx = parsers.search_results(raw)
    cards = businesses.cards([o["id"] for o in organic])
    results = []
    for index, o in enumerate(organic):
        if o.get("rank") is None:              # service searches carry no ranking field
            o["rank"] = ctx["start"] + index + 1
        card = cards.get(o["id"]) or {"id": o["id"]}
        extra = {k: v for k, v in o.items() if not k.startswith("_") and k != "id"}
        if card.get("licenses"):
            extra.pop("licenses", None)
        merged = {"rank": extra.pop("rank")}
        merged.update(card)
        merged.update({k: v for k, v in extra.items()})
        results.append(merged)
    total = min(ctx["total"] or 0, MAX_SEARCH_RESULTS) if ctx["total"] is not None else None
    return {
        "search_title": ctx["title"],
        "did_you_mean": ctx["did_you_mean"],
        "link": page_url,
        "results": results,
        "sponsored_results": [parsers.sponsored_card(s) for s in sponsored] or None,
        "pagination": pagination(page, SEARCH_PAGE_SIZE, total),
    }


def quick_search(query, location, limit):
    result = fetch.gql_one("GetCommunityAnswerBusinessSearch", {"find": query, "near": location, "first": limit})
    if not dig(result, "data", "genericBusinessSearch") and result.get("errors"):
        fetch.raise_for_input(result, "search")
    ids = parsers.quick_search_ids(dig(result, "data"))[:limit]
    by_id = businesses.cards(ids)
    return {"results": [by_id[i] for i in ids if i in by_id]}


def autocomplete(query, location):
    result = fetch.gql_one("GetSuggestions", {"capabilities": [], "prefix": query, "location": location or ""})
    return {"suggestions": parsers.suggestions(dig(result, "data"), "prefetchSuggestions")}


def location_autocomplete(query):
    result = fetch.gql_one("GetLocationSuggestions", {"capabilities": [], "prefix": query})
    return {"suggestions": parsers.suggestions(dig(result, "data"), "locationSuggestions")}


def filters(query, location, category):
    path, page_url = _snippet_path(query, location, category, None, None, None, 1)
    raw = json.loads(fetch.gated_get(path, accept="json", referer=page_url))
    groups = parsers.filters(raw)
    friendly = {v: k for k, v in FEATURES.items()}
    for g in groups:
        for opt in g["options"]:
            opt["feature"] = friendly.get(opt["value"])
    return {"filters": groups}


def categories(query, parent, country):
    rows = refs.categories()
    q = (query or "").lower()
    out = []
    for r in rows:
        if parent and parent not in r["parent_aliases"]:
            continue
        if country and r["countries"] is not None and country not in r["countries"]:
            continue
        if q and q not in r["alias"].lower() and q not in r["title"].lower():
            continue
        out.append({"alias": r["alias"], "title": text(r["title"]), "parent_aliases": r["parent_aliases"] or None,
                    "countries": r["countries"]})
    return {"count": len(out), "categories": out}
