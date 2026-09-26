"""/yelp/businesses/* endpoints. Everything is /gql/batch (open, plain curl)
except the menu page and related businesses (DataDome-gated pages through
fetch.gated_get) and not-recommended reviews (open server-rendered HTML)."""
import json
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from yelp import fetch, parsers
from yelp.shared import biz_link, dig, page_after, pagination, text

# ---- business resolution (alias / id -> encrypted id) ----------------------------------------

_cache = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_SIZE = 5000


def resolve_business(ref):
    """{"encid", "alias", "name"} of a business alias or encrypted id
    (businessByEncidOrAlias accepts both). Raises YelpNotFound."""
    with _cache_lock:
        hit = _cache.get(ref)
        if hit:
            _cache.move_to_end(ref)
            return hit
    result = fetch.gql_one("GetBizPhotosPageData", {"businessEncidOrAlias": ref, "fetchActivePhotosConnection": False})
    biz = dig(result, "data", "businessByEncidOrAlias")
    if not biz or not biz.get("encid"):
        fetch.raise_for_input(result, f"business {ref!r}")
        raise fetch.YelpNotFound(f"business {ref!r} not found on Yelp")
    out = {"encid": biz["encid"], "alias": biz.get("alias") or ref, "name": text(biz.get("name"))}
    with _cache_lock:
        for key in {ref, out["encid"], out["alias"]}:
            _cache[key] = out
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return out


def _business_ref(biz):
    return {"id": biz["encid"], "alias": biz["alias"], "name": biz["name"], "link": biz_link(biz["alias"])}


def _named(ops, results):
    return {name: (r or {}).get("data") for (name, _v), r in zip(ops, results)}


# ---- details ------------------------------------------------------------------------------------

# Attribute aliases asked of GetLocalBusinessJsonLinkedData: the site's own
# list plus the restaurant attributes it only shows in the amenities panel
# (price level, WiFi, alcohol, noise, attire, ambience, meals, ...), all
# verified to answer 2026-09-26.
ATTRIBUTE_ALIASES = [
    "BusinessAcceptsCreditCards", "accepts_credit_cards", "BusinessAcceptsApplePay", "accepts_apple_pay",
    "BusinessAcceptsAndroidPay", "accepts_android_pay", "BusinessAcceptsBitcoin", "accepts_bitcoin", "BusinessParking",
    "WheelchairAccessible", "is_wheelchair_accessible", "GenderNeutralRestrooms", "OutdoorSeating", "HasPoolTable",
    "by_appointment_only", "ByAppointmentOnly", "caters", "Caters", "offers_contactless_delivery",
    "offers_military_discount", "DogsAllowed", "accepts_insurance", "AcceptsInsurance", "Corkage", "BYOBCorkage",
    "RestaurantsPriceRange2", "WiFi", "Alcohol", "NoiseLevel", "RestaurantsAttire", "Ambience", "GoodForMeal",
    "BestNights", "Music", "Smoking", "HappyHour", "RestaurantsGoodForGroups", "GoodForKids", "RestaurantsTakeOut",
    "RestaurantsDelivery", "RestaurantsReservations", "RestaurantsTableService", "HasTV", "BikeParking", "DriveThru",
    "GoodForDancing", "CoatCheck", "DietaryRestrictions", "Open24Hours", "AgesAllowed",
]


def _details_ops(enc, alias):
    return [
        ("GetBizHeaderData", {"BizEncId": enc, "BizFreshnessIsEnabled": True, "IncludeClaimability": True,
                              "RoundingMethod": "NEAREST_TENTH"}),
        ("GetLocalBusinessJsonLinkedData", {"encBizId": enc, "FetchVideoMetadata": False, "MediaItemsLimit": 1,
                                            "ReviewsPerPage": 1, "HasSelectedReview": False, "SelectedReviewEncId": "",
                                            "FetchAuthoritativeAttributes": True, "VideoCarouselItemsLimit": 1,
                                            "FetchVideoCarouselItems": False, "bizAttributeAliases": ATTRIBUTE_ALIASES,
                                            "FetchReviewSnippets": False}),
        ("GetBusinessHours", {"BizEncId": enc}),
        ("GetSpecialHoursAlert", {"BizEncId": enc}),
        ("GetBizContactInfo", {"BizEncId": enc, "ConsumerEditIsEnabled": False}),
        ("GetBizPageProperties", {"BizEncId": enc}),
        ("GetBusinessHealthScoreAlert", {"BizEncId": enc}),
        ("GetFromTheBusiness", {"businessEncid": enc}),
        ("GetBusinessOnTheMenuPopularXData", {"BizEncId": enc, "MaxPopularDishes": 10}),
        ("GetBusinessClaimability", {"BizEncId": enc}),
        ("GetNotRecommendedReviewsProps", {"BizEncId": enc}),
        ("GetBizDetailsMetaHead", {"BizEncId": enc, "RequestUrl": biz_link(alias)}),
        ("GetVibeCheckData", {"BizEncId": enc, "metadataEnabled": True}),
        ("GetVerifiedLicenseData", {"BizEncId": enc}),
        ("getCategoryBreadcrumbsJsonLinkedData", {"BizEncId": enc}),
        ("GetMapBoxV2Data", {"BizEncId": enc, "StaticMapWidth": 600, "StaticMapHeightFull": 300,
                             "StaticMapHeightReduced": 200, "fetchExteriorPhoto": True}),
        ("GetTransactionSectionData", {"BizEncIds": [enc]}),
        ("GetPhotoHeaderDataWithMetadata", {"BizEncId": enc}),
        ("GetReviewSummary", {"BizEncId": enc}),
        ("GetCategoriesAndJobs", {"BizEncId": enc}),
        ("GetBizConsumerAlertsHistory", {"BizEncId": enc}),
        ("GetIsOnlineBusiness", {"BizEncId": enc}),
    ]


def details(business):
    biz = resolve_business(business)
    ops = _details_ops(biz["encid"], biz["alias"])
    results = fetch.gql(ops)
    named = _named(ops, results)
    if not dig(named, "GetBizHeaderData", "business") and not dig(named, "GetLocalBusinessJsonLinkedData", "business"):
        fetch.raise_for_input(results[0], f"business {business!r}")
        raise fetch.YelpUpstreamError(f"yelp returned no data for business {business!r}")
    return parsers.details(named, biz["alias"])


# ---- reviews ------------------------------------------------------------------------------------

REVIEW_SORTS = {"relevance": "RELEVANCE_DESC", "newest": "DATE_DESC", "oldest": "DATE_ASC",
                "highest_rated": "RATING_DESC", "lowest_rated": "RATING_ASC", "elites": "ELITES_DESC"}


def reviews(business, sort_by, rating, query, language, translate_to, page, page_size):
    biz = resolve_business(business)
    variables = {
        "encBizId": biz["encid"], "reviewsPerPage": page_size, "after": page_after(page, page_size),
        "sortBy": REVIEW_SORTS.get(sort_by or "relevance"),
        "ratings": sorted(rating, reverse=True) if rating else [5, 4, 3, 2, 1],
        "queryText": query or "", "isSearching": bool(query),
        "selectedReviewEncId": "", "hasSelectedReview": False,
        "translateLanguageCode": translate_to or "en", "isTranslating": bool(translate_to),
        "reactionsSourceFlow": "businessPageReviewSection", "minConfidenceLevel": "HIGH_CONFIDENCE",
        "highlightType": "", "highlightIdentifier": "", "isHighlighting": False,
        "eliteAllStarSourceFlow": "biz_page_review_feed", "fetchMediaReviewContent": False, "photoSize": "SQUARE_348",
    }
    if language:
        variables["languageCode"] = language      # an explicit null empties keyword search
    result = fetch.gql_one("GetBusinessReviewFeed", variables)
    b = dig(result, "data", "business")
    if not b:
        fetch.raise_for_input(result, f"business {business!r}")
        raise fetch.YelpUpstreamError("yelp returned no review feed")
    items, total, has_next, stats = parsers.review_feed(b)
    pages = pagination(page, page_size, total)
    if total is None:
        pages["total_pages"] = page + 1 if has_next else page
    return {"business": dict(_business_ref(biz), **stats), "reviews": items, "pagination": pages}


NOT_RECOMMENDED_PAGE_SIZE = 10


def not_recommended_reviews(business, page):
    biz = resolve_business(business)
    start = (page - 1) * NOT_RECOMMENDED_PAGE_SIZE
    path = f"/not_recommended_reviews/{biz['alias']}" + (f"?not_recommended_start={start}" if start else "")
    items, total, removed = parsers.not_recommended_reviews(fetch.open_get(path))
    return {"business": _business_ref(biz), "removed_review_count": removed, "reviews": items,
            "pagination": pagination(page, NOT_RECOMMENDED_PAGE_SIZE, total)}


def review_highlights(business):
    biz = resolve_business(business)
    result = fetch.gql_one("GetReviewHighlightsWithPopX", {"encBizId": biz["encid"], "locale": "en_US"})
    if dig(result, "data", "business") is None:
        fetch.raise_for_input(result, f"business {business!r}")
    return {"business": _business_ref(biz), "highlights": parsers.review_highlights(dig(result, "data", "business"))}


def review_topics(business):
    biz = resolve_business(business)
    result = fetch.gql_one("GetReviewTopics", {"encBizId": biz["encid"]})
    if dig(result, "data", "business") is None:
        fetch.raise_for_input(result, f"business {business!r}")
    return {"business": _business_ref(biz), "topics": parsers.review_topics(dig(result, "data", "business"))}


TOPIC_PAGE_SIZE = 20


def topic_reviews(business, topic, page):
    biz = resolve_business(business)
    result = fetch.gql_one("GetFilteredReviews", {"encBizId": biz["encid"], "first": TOPIC_PAGE_SIZE, "topic": topic,
                                                  "after": page_after(page, TOPIC_PAGE_SIZE, string_version=True) or ""})
    b = dig(result, "data", "business")
    if not dig(b, "searchReviewInsights"):
        if "INTERNAL_SERVER_ERROR" in fetch.error_codes(result):
            raise fetch.YelpUpstreamError(f"yelp failed to load the {topic!r} reviews, retry later")
        if result.get("errors"):
            raise fetch.YelpBadRequest(f"no review topic {topic!r} for this business — "
                                       "list its topics with /yelp/businesses/reviews/topics")
        fetch.raise_for_input(result, f"business {business!r}")
    items, total = parsers.topic_reviews(b or {})
    for r in items:
        r["link"] = f"{biz_link(biz['alias'])}?hrid={r['id']}"
    return {"business": _business_ref(biz), "topic": topic, "reviews": items,
            "pagination": pagination(page, TOPIC_PAGE_SIZE, total)}


# ---- photos / dishes / menu ---------------------------------------------------------------------------

def _videos(biz, page, page_size):
    result = fetch.gql_one("GetLightboxData", {
        "BizEncId": biz["encid"], "ItemCount": page_size, "Cursor": page_after(page, page_size), "Tab": "videos",
        "ShouldGetOrderedMediaItems": True, "IncludeBizOwnerVideo": True, "IsSearching": False, "SearchQuery": "",
        "IsFiltering": True, "shouldUseGrouping": False, "fetchMediaReviewContent": False, "reactionsSourceFlow": "mediaDetail"})
    b = dig(result, "data", "business")
    if not b:
        fetch.raise_for_input(result, f"business {biz['alias']!r}")
        raise fetch.YelpUpstreamError("yelp returned no videos")
    items, total, tabs = parsers.lightbox_media(b)
    return {"business": _business_ref(biz), "category": "videos", "categories": tabs or None,
            "photos": items, "pagination": pagination(page, page_size, total)}


def photos(business, category, query, page, page_size):
    biz = resolve_business(business)
    if category == "videos" and not query:
        return _videos(biz, page, page_size)
    tab = None if (category in (None, "all") and not query) else (category or "all")
    variables = {
        "businessEncidOrAlias": biz["encid"], "userEncid": "", "isUserFiltered": False, "resultsPerPage": page_size,
        "after": page_after(page, page_size), "reactionsSourceFlow": "mediaDetail", "searchQuery": query or "",
        "fetchSearchResults": bool(query), "fetchTabResults": tab is not None, "fetchOrderedMediaItems": tab is None,
        "fetchMediaReviewContent": False,
    }
    if tab:
        variables["selectedTab"] = tab
    result = fetch.gql_one("GetBizPhotosMediaGrid", variables)
    b = dig(result, "data", "businessByEncidOrAlias")
    if not b:
        fetch.raise_for_input(result, f"business {business!r}")
        raise fetch.YelpUpstreamError("yelp returned no photos")
    items, total, tabs = parsers.photo_grid(b)
    return {"business": _business_ref(biz), "category": category or "all", "categories": tabs,
            "photos": items, "pagination": pagination(page, page_size, total)}


def popular_dishes(business, limit):
    biz = resolve_business(business)
    result = fetch.gql_one("GetBusinessOnTheMenuPopularXData", {"BizEncId": biz["encid"], "MaxPopularDishes": limit})
    data = dig(result, "data") or {}
    if data.get("business") is None:
        fetch.raise_for_input(result, f"business {business!r}")
    dishes = parsers.popular_dishes(data.get("popularX"))
    chosen = dig(data, "popularX", "carousel", "chosenPopularX") or "Popular Dishes"
    if dishes:
        mentions = fetch.gql_one("GetPopularXMentions", {"BizEncId": biz["encid"], "ChosenPopularX": chosen,
                                                         "Identifiers": [d["id"] for d in dishes if d.get("id")]})
        by_id = parsers.dish_mentions(dig(mentions, "data"))
        for d in dishes:
            d["photos"] = (by_id.get(d["id"]) or {}).get("photos") or None
    menu_biz = data.get("business") or {}
    return {"business": _business_ref(biz), "type": text(chosen), "dishes": dishes,
            "menu": {"yelp_link": dig(menu_biz, "yelpMenu", "url"),
                     "external_link": dig(menu_biz, "externalResources", "menu", "url")}}


def menu(business):
    biz = resolve_business(business)
    result = fetch.gql_one("GetBusinessOnTheMenuPopularXData", {"BizEncId": biz["encid"], "MaxPopularDishes": 1})
    if dig(result, "data", "business") is None:
        fetch.raise_for_input(result, f"business {business!r}")
    menu_biz = dig(result, "data", "business") or {}
    yelp_link = dig(menu_biz, "yelpMenu", "url")
    external = dig(menu_biz, "externalResources", "menu", "url")
    out = {"business": _business_ref(biz), "name": None, "yelp_link": yelp_link, "external_link": external,
           "has_yelp_menu": bool(yelp_link), "sections": []}
    if yelp_link:
        path = "/" + yelp_link.split("://", 1)[-1].split("/", 1)[1]
        parsed = parsers.menu(fetch.gated_get(path, accept="html", referer=biz_link(biz["alias"])))
        out["name"] = parsed["name"]
        out["sections"] = parsed["sections"]
    return out


# ---- Q&A / posts / related -----------------------------------------------------------------------------

QUESTION_PAGE_SIZE = 10


def questions(business, page):
    biz = resolve_business(business)
    result = fetch.gql_one("GetBizQuestionsOverviewContentData", {
        "businessEncid": biz["encid"], "questionsAfter": page_after(page, QUESTION_PAGE_SIZE), "questionsSort": "BEST"})
    b = dig(result, "data", "business")
    if not b:
        fetch.raise_for_input(result, f"business {business!r}")
        raise fetch.YelpUpstreamError("yelp returned no questions")
    items, total = parsers.questions(b)
    return {"business": _business_ref(biz), "questions": items,
            "pagination": pagination(page, QUESTION_PAGE_SIZE, total)}


ANSWER_PAGE_SIZE = 10


def answers(question, page):
    result = fetch.gql_one("GetQuestionDetailsContentData", {
        "questionEncid": question, "answersAfter": page_after(page, ANSWER_PAGE_SIZE), "answersSort": "BEST"})
    data = dig(result, "data") or {}
    if not data.get("businessCommunityQuestion"):
        fetch.raise_for_input(result, f"question {question!r}")
        raise fetch.YelpNotFound(f"question {question!r} not found on Yelp")
    q, items, total = parsers.question_details(data)
    return {"question": q, "answers": items, "pagination": pagination(page, ANSWER_PAGE_SIZE, total)}


POSTS_LIMIT = 50                # businesses carry a handful of posts; the connection ignores offset cursors


def posts(business):
    biz = resolve_business(business)
    # $page is the connection's `first` (a count), not a page number.
    result = fetch.gql_one("GetBusinessPosts", {"encBizId": biz["encid"], "hasUserId": False, "page": POSTS_LIMIT,
                                                "after": None})
    b = dig(result, "data", "business")
    if b is None:
        fetch.raise_for_input(result, f"business {business!r}")
    return {"business": _business_ref(biz), "posts": parsers.posts(b or {})}


def related(business):
    biz = resolve_business(business)
    # A referer of the business page itself hard-blocks (t=bv) this JSON;
    # the site root passes (verified 2026-09-26).
    raw = json.loads(fetch.gated_get(f"/biz/{biz['encid']}/props", accept="json"))
    items, collections = parsers.related(raw)
    return {"business": _business_ref(biz), "related_businesses": items, "collections": collections or None}


# ---- batch --------------------------------------------------------------------------------------------------

def cards(ids, with_contact=True):
    """{encid: card} for up to ~20 encrypted ids (list ops + per-business contact)."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    ops = [("GetResultsSectionData", {"BizEncIds": ids}),
           ("GetStructuredBusinessListData", {"BizEncIds": ids, "FetchPhotosAndCaptions": True, "FetchLongFormAltText": False}),
           ("GetMapData", {"BizEncIds": ids})]
    if with_contact:
        ops += [("GetBizContactInfo", {"BizEncId": i, "ConsumerEditIsEnabled": False}) for i in ids]
    results = fetch.gql(ops)
    named = {}
    for idx, ((name, variables), r) in enumerate(zip(ops, results)):
        key = f"contact:{variables['BizEncId']}" if name == "GetBizContactInfo" else name
        named[key] = (r or {}).get("data")
    return parsers.cards_by_id(named, ids)


def batch(businesses):
    def _resolve(ref):
        try:
            return ref, resolve_business(ref)
        except fetch.YelpNotFound:
            return ref, None
    with ThreadPoolExecutor(8) as pool:
        resolved = list(pool.map(_resolve, businesses))
    ids = [b["encid"] for _ref, b in resolved if b]
    by_id = cards(ids)
    out, missing = [], []
    for ref, b in resolved:
        card = by_id.get(b["encid"]) if b else None
        if card:
            out.append(card)
        else:
            missing.append(ref)
    return {"businesses": out, "not_found": missing or None}

