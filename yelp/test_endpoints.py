"""Live endpoint smoke tests: one call per /yelp/* route against a running
service, with example values proven to return data (2026-09-26). The
listing tooling reads each route's FIRST call from this file's AST as its
working example, so the values stay literals.

Skipped unless YELP_BASE points at a running service:

    ONLY_SCRAPER=yelp python run.py            # or any bottle runner
    YELP_BASE=http://127.0.0.1:6002 python -m pytest yelp/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("YELP_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set YELP_BASE to run live endpoint tests")


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=240)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=240).status_code


def test_search():
    body = call("/yelp/search", query="pizza", location="San Francisco, CA")
    assert len(body["results"]) == 10 and body["results"][0]["name"] and body["total_pages"] == 24
    body = call("/yelp/search", category="italian", location="Chicago, IL", sort_by="highest_rated",
                price="2,3", features="outdoor_seating,free_wifi", page=2)
    assert body["results"] and body["current_page"] == 2


def test_quick_search():
    body = call("/yelp/search/quick", query="coffee", location="Brooklyn, NY", limit=5)
    assert body["results"] and body["results"][0]["name"] and body["results"][0]["address"]["city"]


def test_autocomplete():
    body = call("/yelp/search/autocomplete", query="piz", location="San Francisco, CA")
    assert body["suggestions"][0]["text"]
    body = call("/yelp/locations/autocomplete", query="San Fr")
    assert body["suggestions"][0]["text"].startswith("San Francisco")


def test_filters_and_categories():
    body = call("/yelp/search/filters", query="plumbers", location="Austin, TX")
    assert any(g["options"] for g in body["filters"])
    body = call("/yelp/categories", parent="restaurants", country="GB")
    assert body["count"] > 50 and body["categories"][0]["alias"]


def test_business_details():
    body = call("/yelp/businesses/details", business="gary-danko-san-francisco")
    assert body["id"] == "WavvLdfdP6g8aZTtbBQHTw" and body["hours"]["weekly"] and body["attributes"]
    body = call("/yelp/businesses/details", business="https://www.yelp.com/biz/airco-round-rock-2")
    assert body["licenses"] and body["services"] and body["service_area"]


def test_business_batch():
    body = call("/yelp/businesses/batch", businesses="gary-danko-san-francisco,tonys-pizza-napoletana-san-francisco")
    assert len(body["businesses"]) == 2


def test_reviews():
    body = call("/yelp/businesses/reviews", business="gary-danko-san-francisco", sort_by="newest", page=2)
    assert len(body["reviews"]) == 20 and body["count"] > 5000
    body = call("/yelp/businesses/reviews", business="WavvLdfdP6g8aZTtbBQHTw", query="lobster", translate_to="es", page_size=5)
    assert body["reviews"][0]["translated_text"]
    body = call("/yelp/businesses/reviews/not-recommended", business="gary-danko-san-francisco", page=2)
    assert len(body["reviews"]) == 10
    body = call("/yelp/businesses/reviews/topics", business="gary-danko-san-francisco")
    assert body["topics"]
    body = call("/yelp/businesses/reviews/by-topic", business="gary-danko-san-francisco", topic="service")
    assert body["reviews"]
    body = call("/yelp/businesses/reviews/highlights", business="gary-danko-san-francisco")
    assert body["highlights"]


def test_media_and_menu():
    body = call("/yelp/businesses/photos", business="gary-danko-san-francisco", category="food", page=2)
    assert len(body["photos"]) == 30 and body["categories"]
    body = call("/yelp/businesses/popular-dishes", business="gary-danko-san-francisco", limit=5)
    assert body["dishes"]
    body = call("/yelp/businesses/menu", business="golden-boy-pizza-san-francisco-5")
    assert body["sections"][0]["items"][0]["price"]


def test_questions_posts_related():
    body = call("/yelp/businesses/questions", business="gary-danko-san-francisco")
    assert body["questions"]
    body = call("/yelp/businesses/questions/answers", question="https://www.yelp.com/questions/WavvLdfdP6g8aZTtbBQHTw/2YQo0SgATXjcHt1sI-_taQ")
    assert body["answers"]
    body = call("/yelp/businesses/posts", business="tonys-pizza-napoletana-san-francisco")
    assert body["posts"] and body["posts"][0]["headline"]
    body = call("/yelp/businesses/related", business="gary-danko-san-francisco")
    assert body["related_businesses"]


def test_users():
    body = call("/yelp/users/details", user="CHV3OXUzMbMDZ5A07UGO5A")
    assert body["name"] and body["elite_years"]
    body = call("/yelp/users/reviews", user="CHV3OXUzMbMDZ5A07UGO5A", sort_by="newest")
    assert body["reviews"] and body["reviews"][0]["business"]
    body = call("/yelp/users/photos", user="https://www.yelp.com/user_details?userid=CHV3OXUzMbMDZ5A07UGO5A")
    assert body["photos"]
    body = call("/yelp/users/friends", user="CHV3OXUzMbMDZ5A07UGO5A", sort_by="name")
    assert body["friends"]
    body = call("/yelp/users/following", user="CHV3OXUzMbMDZ5A07UGO5A")
    assert "following" in body
    body = call("/yelp/users/compliments", user="CHV3OXUzMbMDZ5A07UGO5A")
    assert body["compliments"]


def test_events():
    body = call("/yelp/events/search", city="sf", category="music")
    assert body["events"]
    body = call("/yelp/events/details", event=body["events"][0]["link"])
    assert body["name"] and body["starts_at"]


def test_errors():
    assert status("/yelp/businesses/details", business="this-business-does-not-exist-zzzz") == 404
    assert status("/yelp/businesses/details", business="https://www.google.com/biz/x") == 400
    assert status("/yelp/users/details", user="AAAAAAAAAAAAAAAAAAAAAA") == 404
    assert status("/yelp/search", location="San Francisco, CA") == 400
