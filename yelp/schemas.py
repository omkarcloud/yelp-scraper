"""Marshmallow request schemas for every /yelp/* route.

Generic fields come from the shared top-level schema_fields.py; this module
adds the Yelp resolvers (refs.py) and the per-route schemas. Every schema's
load() output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrLinkField convention, never a
sibling `url` / `id` pair):
  business    alias | 22-char id | any yelp.* business link (/biz/, /biz_photos/, /menu/, ...)
  businesses  a comma list of the above (batch)
  user        22-char id | profile link (/user_details?userid=...)
  question    22-char id | question link (/questions/<business>/<question>)
  event       slug | event link
  city        events city slug (sf, la, nyc, ...) | an /events/<city> link
  category    alias | title | a search link with cflt=
"""
import re

from marshmallow import ValidationError, fields, validate, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, CountryCodeField, DateField, Flag, LanguageCodeField,
                           PageField, PageSizeField, QueryField, RefField, StrippedString)
from yelp import refs

# Choice tables as literals; the publishing tooling reads enums from this file's AST.
SEARCH_SORTS = ["recommended", "highest_rated", "most_reviewed"]
REVIEW_SORTS = ["relevance", "newest", "oldest", "highest_rated", "lowest_rated", "elites"]
USER_REVIEW_SORTS = ["newest", "oldest", "highest_rated", "lowest_rated"]
FRIEND_SORTS = ["newest", "oldest", "name", "name_desc", "recently_reviewed"]
EVENT_CATEGORIES = ["music", "visual_arts", "performing_arts", "film", "lectures_and_books", "fashion", "food_and_drink",
                    "festivals_and_fairs", "charities", "sports_and_active_life", "nightlife", "kids_and_family", "other"]
EVENT_SORTS = ["popular", "recently_added", "free"]
PRICE_LEVELS = ["1", "2", "3", "4"]
RATINGS = ["1", "2", "3", "4", "5"]
MAX_SEARCH_PAGE = 24          # Yelp serves at most 240 results (10 per page) per query
MAX_REVIEW_PAGE_SIZE = 49     # a 50-review page answers null


# ---- id-or-link fields ---------------------------------------------------------------------

class BusinessField(RefField):
    resolver = staticmethod(refs.business_ref)


class BusinessesField(RefField):
    resolver = staticmethod(refs.business_refs)


class UserField(RefField):
    resolver = staticmethod(refs.user_ref)


class QuestionField(RefField):
    resolver = staticmethod(refs.question_ref)


class EventField(RefField):
    resolver = staticmethod(refs.event_ref)


class CityField(RefField):
    resolver = staticmethod(refs.event_city)


class CategoryField(RefField):
    resolver = staticmethod(refs.category_alias)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class FeaturesField(fields.Field):
    """Comma list of search features: friendly names (outdoor_seating,
    free_wifi, open_now, ...) or raw Yelp tokens as /yelp/search/filters
    lists them (OutdoorSeating, WiFi.free, job_plumbing_repair, ...)."""
    _TOKEN = re.compile(r"^[A-Za-z][\w.:]{1,80}$")

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        from yelp.search import FEATURES
        lookup = {k.lower(): v for k, v in FEATURES.items()}
        raw_tokens = set(FEATURES.values())
        out = []
        for item in str(value).split(","):
            item = item.strip()
            if not item:
                continue
            token = lookup.get(item.lower()) or (item if item in raw_tokens or self._TOKEN.match(item) else None)
            if token is None:
                raise ValidationError(f"Unknown feature {item!r}. Use one of: {', '.join(sorted(FEATURES))}, "
                                      "or a value from /yelp/search/filters.")
            if token not in out:
                out.append(token)
        if len(out) > 15:
            raise ValidationError("At most 15 features.")
        return out or None


def _page(max_page=1000):
    return PageField(max_page=max_page)


# ---- search --------------------------------------------------------------------------------------

class SearchSchema(BaseSchema):
    query = StrippedString(load_default=None, validate=validate.Length(max=200))
    location = QueryField(max_length=200)
    category = CategoryField()
    sort_by = ChoiceField(SEARCH_SORTS, load_default="recommended")
    price = CommaListField(allowed=PRICE_LEVELS, value_map={p: int(p) for p in PRICE_LEVELS}, max_items=4)
    features = FeaturesField()
    page = _page(MAX_SEARCH_PAGE)

    @validates_schema
    def _query_or_category(self, data, **kwargs):
        if not data.get("query") and not data.get("category"):
            raise ValidationError("Pass a query, a category, or both.", "query")


class QuickSearchSchema(BaseSchema):
    query = QueryField()
    location = QueryField(max_length=200)
    limit = PageSizeField(default=10, max_size=25)


class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100)
    location = StrippedString(load_default=None, validate=validate.Length(max=200))


class LocationAutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100)


class FiltersSchema(BaseSchema):
    query = StrippedString(load_default=None, validate=validate.Length(max=200))
    location = QueryField(max_length=200)
    category = CategoryField()


class CategoriesSchema(BaseSchema):
    query = StrippedString(load_default=None, validate=validate.Length(max=100))
    parent = CategoryField()
    country = CountryCodeField()


# ---- businesses ----------------------------------------------------------------------------------

class BusinessSchema(BaseSchema):
    business = BusinessField()


class BusinessPageSchema(BaseSchema):
    business = BusinessField()
    page = _page()


class BatchSchema(BaseSchema):
    businesses = BusinessesField()


class ReviewsSchema(BaseSchema):
    business = BusinessField()
    sort_by = ChoiceField(REVIEW_SORTS, load_default="relevance")
    rating = CommaListField(allowed=RATINGS, value_map={r: int(r) for r in RATINGS}, max_items=5)
    query = StrippedString(load_default=None, validate=validate.Length(max=100))
    language = LanguageCodeField(allow_locale=False)
    translate_to = LanguageCodeField(allow_locale=False)
    page = _page()
    page_size = PageSizeField(default=20, max_size=MAX_REVIEW_PAGE_SIZE)


class TopicReviewsSchema(BaseSchema):
    business = BusinessField()
    topic = QueryField(max_length=100)
    page = _page()


class PhotosSchema(BaseSchema):
    business = BusinessField()
    category = StrippedString(load_default=None, validate=validate.Regexp(r"^[a-z_]{2,40}$", error="Must be a photo category alias (food, drink, interior, outside, menu, videos, ...)."))
    query = StrippedString(load_default=None, validate=validate.Length(max=100))
    page = _page()
    page_size = PageSizeField(default=30, max_size=100)


class PopularDishesSchema(BaseSchema):
    business = BusinessField()
    limit = PageSizeField(default=20, max_size=50)


class AnswersSchema(BaseSchema):
    question = QuestionField()
    page = _page()


# ---- users ---------------------------------------------------------------------------------------------

class UserSchema(BaseSchema):
    user = UserField()


class UserPageSchema(BaseSchema):
    user = UserField()
    page = _page()
    page_size = PageSizeField(default=20, max_size=50)


class UserReviewsSchema(UserPageSchema):
    sort_by = ChoiceField(USER_REVIEW_SORTS, load_default=None)
    category = CategoryField()
    query = StrippedString(load_default=None, validate=validate.Length(max=100))


class UserFriendsSchema(UserPageSchema):
    sort_by = ChoiceField(FRIEND_SORTS, load_default="newest")


# ---- events -----------------------------------------------------------------------------------------------

class EventSearchSchema(BaseSchema):
    city = CityField()
    category = ChoiceField(EVENT_CATEGORIES, load_default=None)
    sort_by = ChoiceField(EVENT_SORTS, load_default="popular")
    start_date = DateField()
    end_date = DateField()
    official_only = Flag(load_default=False)
    page = _page(100)


class EventSchema(BaseSchema):
    event = EventField()
