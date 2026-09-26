"""The 28 Yelp endpoints. Every path is served with and without the `/yelp`
prefix, so code generated against the hosted API (paths like
/businesses/details) runs unchanged against this server.

Each route validates its query with the marshmallow schema in
yelp/schemas.py (one param per input: a business alias OR its id OR any
yelp.com link, ...) and calls the function that returns the JSON. Paged
routes answer in the hosted API's shape: count / per_page / current_page /
total_pages / next / previous, then the data."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from yelp import businesses, events, search, users
from yelp import schemas as S


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so a UTF-8 "Café" would arrive as "CafÃ©")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    host = request.headers.get("Host") or "localhost"
    return f"{request.urlparts.scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, raw_params):
    """Lift the function's `pagination` block into the flat shape with
    next / previous links built from the caller's own query params."""
    pagination = result.pop("pagination", None) or {}
    page = _as_int(pagination.get("page")) or _as_int(raw_params.get("page")) or 1
    total_pages = max(_as_int(pagination.get("total_pages")), 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, raw_params, page + 1 if page < total_pages else None),
        "previous": _page_link(path, raw_params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(path, schema, fn, paginated):
    """Validate, run, and map errors: bad params -> 400, not found -> 404,
    blocked -> 502, anything else -> 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = fn(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"yelp rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"yelp blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"yelp {path.strip('/')} failed: {e}"}, 502)
    except Exception as e:                 # retries exhausted, parser surprise
        return json_response({"error": f"yelp {path.strip('/')} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


# public path -> (schema, function, paginated), in the documented order
ENDPOINTS = [
    ("/businesses/details", S.BusinessSchema, businesses.details, False),
    ("/search/autocomplete", S.AutocompleteSchema, search.autocomplete, False),
    ("/locations/autocomplete", S.LocationAutocompleteSchema, search.location_autocomplete, False),
    ("/search", S.SearchSchema, search.search, True),
    ("/search/quick", S.QuickSearchSchema, search.quick_search, False),
    ("/search/filters", S.FiltersSchema, search.filters, False),
    ("/categories", S.CategoriesSchema, search.categories, False),
    ("/businesses/batch", S.BatchSchema, businesses.batch, False),
    ("/businesses/reviews", S.ReviewsSchema, businesses.reviews, True),
    ("/businesses/reviews/not-recommended", S.BusinessPageSchema, businesses.not_recommended_reviews, True),
    ("/businesses/reviews/topics", S.BusinessSchema, businesses.review_topics, False),
    ("/businesses/reviews/by-topic", S.TopicReviewsSchema, businesses.topic_reviews, True),
    ("/businesses/reviews/highlights", S.BusinessSchema, businesses.review_highlights, False),
    ("/businesses/photos", S.PhotosSchema, businesses.photos, True),
    ("/businesses/popular-dishes", S.PopularDishesSchema, businesses.popular_dishes, False),
    ("/businesses/menu", S.BusinessSchema, businesses.menu, False),
    ("/businesses/questions", S.BusinessPageSchema, businesses.questions, True),
    ("/businesses/questions/answers", S.AnswersSchema, businesses.answers, True),
    ("/businesses/posts", S.BusinessSchema, businesses.posts, False),
    ("/businesses/related", S.BusinessSchema, businesses.related, False),
    ("/users/details", S.UserSchema, users.details, False),
    ("/users/reviews", S.UserReviewsSchema, users.reviews, True),
    ("/users/photos", S.UserPageSchema, users.photos, True),
    ("/users/friends", S.UserFriendsSchema, users.friends, True),
    ("/users/following", S.UserPageSchema, users.following, True),
    ("/users/compliments", S.UserPageSchema, users.compliments, True),
    ("/events/search", S.EventSearchSchema, events.search, True),
    ("/events/details", S.EventSchema, events.details, False),
]


def mount(path, schema, fn, paginated):
    """Serve one endpoint at /path and /yelp/path."""
    def handler():
        return call(path, schema, fn, paginated)
    handler.__name__ = "yelp_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/yelp" + path, method="GET")(handler)


for _path, _schema, _fn, _paginated in ENDPOINTS:
    mount(_path, _schema, _fn, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _, _ in ENDPOINTS]})
