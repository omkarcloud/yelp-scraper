"""Cache TTL per /yelp/* endpoint (cache.py, keyed on the validated params —
marshmallow fills the defaults, so `?page=1` and no `page` share a row, and
an alias / id / link form of the same business resolve to one key only when
they are the same string; different forms simply cache separately).

Tiers follow how fast each surface moves: business facts (hours, amenities,
licenses) change rarely but ratings / counts tick daily; review feeds and
search rankings move within hours; category tables and autocomplete almost
never."""
from datetime import timedelta

# --- search ----------------------------------------------------------------------------
SEARCH_CACHE = timedelta(hours=12)
QUICK_SEARCH_CACHE = timedelta(days=1)
AUTOCOMPLETE_CACHE = timedelta(days=7)
LOCATION_AUTOCOMPLETE_CACHE = timedelta(days=30)
FILTERS_CACHE = timedelta(days=7)
CATEGORIES_CACHE = timedelta(days=30)

# --- businesses ----------------------------------------------------------------------------
DETAILS_CACHE = timedelta(days=1)
BATCH_CACHE = timedelta(days=1)
REVIEWS_CACHE = timedelta(hours=6)
NOT_RECOMMENDED_CACHE = timedelta(days=1)
HIGHLIGHTS_CACHE = timedelta(days=3)
TOPICS_CACHE = timedelta(days=3)
TOPIC_REVIEWS_CACHE = timedelta(days=1)
PHOTOS_CACHE = timedelta(days=1)
DISHES_CACHE = timedelta(days=3)
MENU_CACHE = timedelta(days=3)
QUESTIONS_CACHE = timedelta(days=1)
POSTS_CACHE = timedelta(days=1)
RELATED_CACHE = timedelta(days=3)

# --- users ----------------------------------------------------------------------------------
USER_CACHE = timedelta(days=1)
USER_LIST_CACHE = timedelta(hours=12)

# --- events ---------------------------------------------------------------------------------
EVENTS_CACHE = timedelta(hours=6)
EVENT_CACHE = timedelta(days=1)
