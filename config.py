"""Configuration for the Yelp Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT               port the API listens on (default 8000)

    YELP_PROXY         optional proxy URL, e.g. http://user:pass@host:port.
                       Business details, reviews, photos, dishes, Q&A, users,
                       events and autocomplete run on your own IP out of the
                       box. Yelp pauses an IP after a few hundred calls in a
                       few minutes; when that happens those calls move to
                       this proxy for 30 minutes. Search, search filters,
                       menus and related businesses are behind DataDome and
                       always need it (together with CAPSOLVER_API_KEY).
                       Use a STICKY US residential proxy: put `{session}`
                       where your provider takes a session id, e.g.
                       http://user-session-{session}:pass@host:port — a fresh
                       random id (= a fresh IP) is filled in per session.

    CAPSOLVER_API_KEY  needed for search, search filters, menus and related
                       businesses. DataDome answers every new IP with a
                       captcha; CapSolver solves it (~4 s, through your
                       YELP_PROXY) and one solve then serves dozens of calls:
                       https://dashboard.capsolver.com/passport/register?inviteCode=lvdYBC4sYKRm

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os
import random
import string
import tempfile

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks.
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# --- captcha solving --------------------------------------------------------
CAPSOLVER_API_KEY = os.environ.get("CAPSOLVER_API_KEY", "").strip()
# Our CapSolver developer app id: CapSolver pays us a small commission on the
# captchas you solve, at no extra cost to you (you pay CapSolver's normal price).
CAPSOLVER_APP_ID = "DC601421-43D5-45E4-9FDB-B3BAF7A2C3FD"

# --- proxy ------------------------------------------------------------------
YELP_PROXY = os.environ.get("YELP_PROXY", "").strip() or None


def _proxy():
    """YELP_PROXY with `{session}` filled in (a new sticky IP), or None."""
    if not YELP_PROXY:
        return None
    session = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return YELP_PROXY.replace("{session}", session)


def yelp_proxy():
    """The exit for the DataDome identity (search, menus, related)."""
    return _proxy()


def yelp_open_proxy(fallback=False):
    """The exit for everything else: your own IP, or YELP_PROXY once Yelp has
    paused your IP (fallback=True)."""
    return _proxy() if fallback else None


def yelp_browser_proxy():
    return None


# --- DataDome identity (search, menus, related) -------------------------------
# CapSolver solves DataDome only for these Chrome user agents (Windows Chrome 140-153).
YELP_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
YELP_SEC_CH_UA = '"Chromium";v="153", "Google Chrome";v="153", "Not.A/Brand";v="99"'
YELP_IDENTITY_ATTEMPTS = 4            # fresh proxy IPs tried per call
YELP_REQUESTS_PER_IDENTITY = 400      # retire a healthy identity after this many calls
YELP_SOLVE_TIMEOUT = 90               # seconds to wait for one CapSolver task
YELP_BROWSER_FALLBACK = False         # the hosted API's last-resort browser is not part of this package
YELP_BROWSER_IDLE_SECONDS = 300

# --- your own IP / proxy for everything else ------------------------------------
YELP_OPEN_PROXY_COUNTRY = None                          # None = your own IP first
YELP_OPEN_FALLBACK_PROXY_COUNTRY = "us" if YELP_PROXY else None   # switch to YELP_PROXY when paused
YELP_OPEN_REQUESTS_PER_EXIT = 500
YELP_OPEN_EXIT_POOL = 3
YELP_DIRECT_COOLDOWN = 1800           # seconds your IP rests after Yelp pauses it
YELP_OPEN_MAX_ATTEMPTS = 4
YELP_GQL_WORKERS = 4

# --- GraphQL query ids ----------------------------------------------------------
# Yelp's GraphQL only runs pre-registered queries. When Yelp changes one, the
# scraper re-reads the ids from Yelp's own JavaScript (at most every 10 min)
# and keeps them in this file across restarts.
YELP_DOCIDS_REFRESH_INTERVAL = 600
YELP_DOCIDS_FILE = os.path.join(tempfile.gettempdir(), "yelp_docids.json")
YELP_SEED_BUSINESS = "gary-danko-san-francisco"
YELP_SEED_USER = "CHV3OXUzMbMDZ5A07UGO5A"
