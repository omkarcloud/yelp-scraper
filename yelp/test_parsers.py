"""Offline tests for the Yelp endpoints + parsers, replaying recorded raw
upstream responses (yelp/fixtures/<case>.json.gz "cassettes").

Each case runs a real endpoint function with fetch.gql / fetch.gated_get /
fetch.open_get patched to answer from the cassette (keyed on the exact call
arguments), so the whole path — variables, pagination cursors, merging,
parsing — is exercised without network.

    python -m pytest yelp/test_parsers.py -q                  # replay (offline)
    YELP_RECORD=1 python -m pytest yelp/test_parsers.py -q    # re-record live
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yelp import businesses, events, fetch, parsers, refs, search, shared, users  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
RECORD = os.environ.get("YELP_RECORD") == "1"
B = "gary-danko-san-francisco"
PLUMBER = "fTydDF3IFJE1cqon9tmzAw"
U = "CHV3OXUzMbMDZ5A07UGO5A"
QUESTION = "2YQo0SgATXjcHt1sI-_taQ"


def _key(fn, args):
    return fn + ":" + json.dumps(args, sort_keys=True, default=str)


@pytest.fixture
def cassette(monkeypatch, request):
    """Patch the transport to record (YELP_RECORD=1) or replay one case."""
    path = os.path.join(FIXTURES, request.node.name.replace("test_", "") + ".json.gz")
    real = {"gql": fetch.gql, "gated_get": fetch.gated_get, "open_get": fetch.open_get}
    tape = {}
    if not RECORD:
        if not os.path.exists(path):
            pytest.skip(f"no cassette {os.path.basename(path)} (record with YELP_RECORD=1)")
        with gzip.open(path, "rt") as f:
            tape = json.load(f)
    businesses._cache.clear()

    def wrap(name):
        def call(*args, **kwargs):
            key = _key(name, [list(args), kwargs])
            if RECORD:
                out = real[name](*args, **kwargs)
                tape[key] = out
                return out
            if key not in tape:
                raise AssertionError(f"cassette miss: {key[:300]}")
            return tape[key]
        return call

    for name in real:
        monkeypatch.setattr(fetch, name, wrap(name))
    monkeypatch.setattr(fetch, "gql_one", lambda n, v: fetch.gql([(n, v)])[0])
    yield
    if RECORD:
        os.makedirs(FIXTURES, exist_ok=True)
        with gzip.open(path, "wt") as f:
            json.dump(tape, f)


# ---- businesses --------------------------------------------------------------------------------

def test_details_restaurant(cassette):
    d = businesses.details(B)
    assert d["id"] == "WavvLdfdP6g8aZTtbBQHTw" and d["alias"] == B and d["link"].endswith(B)
    assert d["rating"] > 3 and d["review_count"] > 5000 and d["price_level"] == 4
    assert set(d["rating_distribution"]) == {"1", "2", "3", "4", "5"}
    assert d["address"]["postal_code"] == "94109" and d["coordinates"]["latitude"] > 37
    assert d["categories"][0]["path"] and d["hours"]["weekly"] and d["timezone"] == "America/Los_Angeles"
    assert d["attributes"]["wifi"] == "free" and isinstance(d["attributes"]["parking"], list)
    assert d["amenities"] and d["health_inspections"][0]["date"]
    assert d["popular_dishes"][0]["name"] and d["vibe"]["tags"]
    assert all(g["alias"] != "all" for g in d["vibe"]["photo_groups"])


def test_details_service_business(cassette):
    d = businesses.details(PLUMBER)
    assert d["service_area"] and d["licenses"][0]["number"] and d["services"][0]["name"]
    assert d["messaging"]["type"] == "request_quote" and d["portfolio"]
    assert d["website"]["link"].startswith("http") and d["about"]["year_established"]


def test_reviews(cassette):
    r = businesses.reviews(B, "newest", None, None, None, None, 2, 5)
    assert len(r["reviews"]) == 5 and r["pagination"]["total_count"] > 5000
    rv = r["reviews"][0]
    assert rv["id"] and rv["created_at"].endswith("Z") and rv["author"]["link"].startswith("https://www.yelp.com/user_details")
    dates = [x["date"] for x in r["reviews"]]
    assert dates == sorted(dates, reverse=True)


def test_reviews_search_and_translate(cassette):
    r = businesses.reviews(B, "relevance", None, "lobster", None, "es", 1, 5)
    assert r["reviews"] and all("lobster" in (x["text"] or "").lower() for x in r["reviews"])
    assert r["pagination"]["total_count"] is None and r["pagination"]["total_pages"] == 2
    assert r["reviews"][0]["translated_text"]


def test_reviews_rating_filter(cassette):
    r = businesses.reviews(B, "relevance", [1, 2], None, None, None, 1, 10)
    assert {x["rating"] for x in r["reviews"]} <= {1, 2}


def test_not_recommended(cassette):
    r = businesses.not_recommended_reviews(B, 2)
    assert len(r["reviews"]) == 10 and r["pagination"]["total_count"] > 1000 and r["removed_review_count"]
    assert r["reviews"][0]["author"]["review_count"] is not None and r["reviews"][0]["date"]


def test_review_topics_and_by_topic(cassette):
    t = businesses.review_topics(B)
    assert {x["name"] for x in t["topics"]} >= {"food", "service"}
    r = businesses.topic_reviews(B, "food", 2)
    assert r["reviews"] and r["reviews"][0]["matched_snippet"] and r["pagination"]["total_count"]


def test_review_highlights(cassette):
    h = businesses.review_highlights(B)["highlights"]
    assert h and h[0]["phrase"] and h[0]["review_count"]


def test_photos(cassette):
    p = businesses.photos(B, None, None, 1, 5)
    assert len(p["photos"]) == 5 and p["photos"][0]["link"].endswith("/o.jpg") and p["categories"]
    v = businesses.photos(B, "videos", None, 1, 2)
    assert v["photos"][0]["type"] == "video" and v["photos"][0]["link"].endswith(".mp4")


def test_popular_dishes(cassette):
    d = businesses.popular_dishes(B, 3)
    assert len(d["dishes"]) == 3 and d["dishes"][0]["photos"] and d["dishes"][0]["rating"]


def test_menu(cassette):
    m = businesses.menu("golden-boy-pizza-san-francisco-5")
    item = m["sections"][0]["items"][0]
    assert m["has_yelp_menu"] and item["price"] > 0 and item["currency"] == "USD"
    assert businesses.menu(B)["has_yelp_menu"] is False


def test_questions_and_answers(cassette):
    q = businesses.questions(B, 1)
    assert q["questions"] and q["pagination"]["total_count"]
    a = businesses.answers(QUESTION, 1)
    assert a["question"]["text"] and a["answers"] and a["answers"][0]["created_at"]


def test_posts(cassette):
    p = businesses.posts("tonys-pizza-napoletana-san-francisco")["posts"]
    assert p and p[0]["headline"] and p[0]["created_at"].endswith("Z") and p[0]["photo_link"].endswith("/o.jpg")


def test_related(cassette):
    r = businesses.related(B)
    assert r["related_businesses"] and r["related_businesses"][0]["link"]


def test_batch(cassette):
    r = businesses.batch([B, PLUMBER, "not-a-real-biz-xyz"])
    assert {b["id"] for b in r["businesses"]} == {"WavvLdfdP6g8aZTtbBQHTw", PLUMBER}
    assert r["not_found"] == ["not-a-real-biz-xyz"]
    assert all(b["phone"] and b["coordinates"] for b in r["businesses"])


# ---- search ------------------------------------------------------------------------------------------

def test_search(cassette):
    s = search.search("pizza", "San Francisco, CA", None, "recommended", None, None, 2)
    assert len(s["results"]) == 10 and s["results"][0]["rank"] == 11
    assert s["results"][0]["name"] and s["results"][0]["address"]["state"] == "CA"
    assert s["pagination"]["total_pages"] == 24


def test_search_filters_and_services(cassette):
    s = search.search(None, "San Francisco, CA", "italian", "highest_rated", [2, 3], ["OutdoorSeating"], 1)
    assert s["results"] and s["pagination"]["total_count"] < 240
    s = search.search("plumbers", "Austin, TX", None, "recommended", None, None, 1)
    assert s["results"][0]["rank"] == 1


def test_quick_search_and_autocomplete(cassette):
    q = search.quick_search("pizza", "San Francisco, CA", 5)
    assert 0 < len(q["results"]) <= 5 and q["results"][0]["name"]
    a = search.autocomplete("piz", "San Francisco, CA")
    assert a["suggestions"][0]["text"]
    loc = search.location_autocomplete("San Fr")
    assert loc["suggestions"][0]["text"].startswith("San Francisco")


def test_filters(cassette):
    groups = search.filters("pizza", "San Francisco, CA", None)["filters"]
    assert any(g["group"] == "price" for g in groups)
    assert any(o["feature"] == "outdoor_seating" for g in groups for o in g["options"])


# ---- users ----------------------------------------------------------------------------------------------

def test_user(cassette):
    u = users.details(U)
    assert u["name"] and u["elite_years"] and u["compliments"] and u["review_count"] > 1000
    r = users.reviews(U, "highest_rated", None, None, 1, 3)
    assert len(r["reviews"]) == 3 and r["reviews"][0]["business"]["name"]
    r = users.reviews(U, None, None, "noodles", 1, 2)
    assert r["reviews"] and r["reviews"][0]["matched_snippet"]
    assert users.photos(U, 1, 2)["photos"][0]["business"]["name"]
    assert users.friends(U, "name", 1, 2)["friends"][0]["name"]
    assert users.following(U, 1, 2)["following"]
    assert users.compliments(U, 1, 2)["compliments"][0]["type"]


# ---- events ---------------------------------------------------------------------------------------------

def test_events(cassette):
    e = events.search("sf", None, "popular", None, None, False, 1)
    assert len(e["events"]) == 15 and e["events"][0]["starts_at"].endswith("Z")
    d = events.details(e["events"][0]["id"])
    assert d["name"] and d["starts_at"] and d["venue"]


# ---- pure helpers (no cassette) ---------------------------------------------------------------------------

def test_refs():
    assert refs.business_ref("https://www.yelp.com/biz/gary-danko-san-francisco?osq=pizza") == B
    assert refs.business_ref("https://m.yelp.ca/biz_photos/gary-danko-san-francisco?tab=food") == B
    assert refs.business_ref("WavvLdfdP6g8aZTtbBQHTw") == "WavvLdfdP6g8aZTtbBQHTw"
    assert refs.user_ref("https://www.yelp.com/user_details?userid=CHV3OXUzMbMDZ5A07UGO5A") == U
    assert refs.question_ref(f"https://www.yelp.com/questions/WavvLdfdP6g8aZTtbBQHTw/{QUESTION}") == QUESTION
    assert refs.category_alias("Italian") == "italian"
    assert refs.category_alias("https://www.yelp.com/search?cflt=pizza&find_loc=SF") == "pizza"
    assert refs.event_city("https://www.yelp.com/events/sf/browse?c=1") == "sf"
    for bad in ("https://google.com/biz/x", "", "has space"):
        with pytest.raises(ValueError):
            refs.business_ref(bad)


def test_shared_helpers():
    assert shared.utc_datetime("2026-08-17T15:17:33-07:00") == "2026-08-17T22:17:33Z"
    assert shared.utc_datetime("2026-06-04T07:00:00.000Z") == "2026-06-04T07:00:00Z"
    assert shared.photo_link("https://s3-media0.fl.yelpcdn.com/bphoto/abc/348s.jpg") == \
        "https://s3-media0.fl.yelpcdn.com/bphoto/abc/o.jpg"
    assert shared.price_level("$$$") == 3 and shared.price_level("££") == 2 and shared.price_level("x$") is None
    assert shared.money("$16.25") == (16.25, "USD")
    assert shared.page_after(1, 10) is None
    assert shared.offset_cursor(9) == "eyJ2ZXJzaW9uIjoxLCJ0eXBlIjoib2Zmc2V0Iiwib2Zmc2V0Ijo5fQ"
    assert shared.us_date("Jun 7, 2024") == "2024-06-07" and shared.elite_year("26") == 2026


def test_parsers_tolerate_empty_input():
    assert parsers.details({}, "x")["alias"] == "x"
    assert parsers.review_feed({})[0] == []
    assert parsers.search_results({})[0] == []
    assert parsers.menu("")["sections"] == []
    assert parsers.not_recommended_reviews("")[0] == []
    assert parsers.events_list("") == []
    assert parsers.event_details("", "a-b")["id"] == "a-b"
    assert parsers.user_profile({})["id"] is None
    assert parsers.address(None)["formatted"] is None
