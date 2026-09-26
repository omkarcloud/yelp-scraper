"""Yelp transport: plain curl_cffi everywhere, CapSolver for DataDome,
headful patchright as the last resort. Validated 2026-09-26.

  gql(ops)            POST www.yelp.com/gql/batch — persisted queries only
                      (docids.py), max 10 ops per POST, OPEN to any egress
                      (no cookie / CSRF / DataDome). Direct by default; a
                      transport failure / 429 / 5xx is retried on a
                      residential exit (config.yelp_open_proxy). A bare 403
                      "Forbidden" = a documentId Yelp no longer knows: the
                      batch is split to find the stale op, docids.refresh()
                      re-mines the ids from the site's JS and the op is
                      retried once.
  gated_get(path)     A DataDome-gated page (/search/snippet JSON, /menu,
                      /biz/<id>/props, /biz/<alias>) through ONE shared
                      identity: a sticky residential exit + a `datadome`
                      cookie minted by a CapSolver DatadomeSliderTask solved
                      THROUGH that exit with config.YELP_USER_AGENT (a Windows
                      Chrome UA — CapSolver refuses others). Every exit is
                      challenged on its first call (t=fe captcha or t=it
                      interstitial); one solve then served 35/35 mixed calls
                      incl. search pagination. A new challenge re-solves on
                      the same exit; a hard block (t=bv) or a failed solve
                      retires the exit. HTTP/1.1 is forced: HTTP/2 through
                      the proxy truncated ~1 in 4 large bodies at a 16 KB
                      boundary. When every attempt fails (or there is no
                      CapSolver key) a headful patchright Chrome runs the call
                      as an in-page fetch — search page 1 works there, deeper
                      pages are captcha-gated for an unsolved browser too.
  open_get(path)      Open server-rendered pages (/not_recommended_reviews,
                      /events, /questions, /user_details) over direct curl,
                      falling back to gated_get if DataDome ever challenges.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  YelpUpstreamError  transport failure / 5xx / unexpected body — retryable
  YelpBlocked        DataDome challenge on every exit              — retryable
  YelpBadRequest     upstream rejected the params (400)            — never retried
  YelpNotFound       business / user / page does not exist         — never retried
"""
import json
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from yelp import docids

SITE = "https://www.yelp.com"
GQL_URL = SITE + "/gql/batch"
IMPERSONATE = "chrome"
GQL_TIMEOUT = (10, 40)
PAGE_TIMEOUT = (10, 45)
MAX_OPS_PER_BATCH = 10          # an 11-op batch answers 400
CAPSOLVER_API = "https://api.capsolver.com"
CAPTCHA_URL_RE = re.compile(r'https://geo\.captcha-delivery\.com/(?:captcha|interstitial)/[^"\'\s<>]+')
DD_OBJECT_RE = re.compile(r"var\s+dd\s*=\s*(\{[^}]*\})")
DD_MARKERS = ("captcha-delivery.com", "var dd=")
EDGE_LIMIT_RETRIES = 3          # empty Fastly 403s retried on the same identity before a new exit
EDGE_LIMIT_BACKOFF = 1.5        # seconds x retry number


class YelpUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected body — retryable."""


class YelpBlocked(YelpUpstreamError, Blocked):
    """DataDome challenge / block on every exit — retryable later."""


class YelpBadRequest(BadRequest):
    """Yelp rejected the params (HTTP 400 / GraphQL BAD_USER_INPUT)."""


class YelpNotFound(NotFound):
    """The business / user / question / page does not exist."""


def dump_debug(name, text):
    """Write a raw response to $YELP_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("YELP_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text if isinstance(text, str) else json.dumps(text))
        except OSError:
            pass


# ---- curl sessions (one per thread per egress; a curl handle is never shared) -----

_local = threading.local()


def _session(key, proxy):
    from curl_cffi import requests as curl_requests
    store = getattr(_local, "sessions", None)
    if store is None:
        store = _local.sessions = OrderedDict()
    sess = store.get(key)
    if sess is None:
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        store[key] = sess
        while len(store) > 6:
            _, old = store.popitem(last=False)
            try:
                old.close()
            except Exception:
                pass
    else:
        store.move_to_end(key)
    return sess


def _drop_session(key):
    store = getattr(_local, "sessions", None) or {}
    sess = store.pop(key, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _http11():
    from curl_cffi import CurlHttpVersion
    return CurlHttpVersion.V1_1


# ---- open-surface egress (gql + open pages) ------------------------------------------------
# Direct egress until Yelp's IP block (a 503 "This page is not available"
# page, or 429) — then direct rests for YELP_DIRECT_COOLDOWN seconds and
# calls ride per-thread sticky residential exits, each retired on its own
# first block or after YELP_OPEN_REQUESTS_PER_EXIT calls.

IP_BLOCK_MARKER = "This page is not available"
_direct_blocked_until = 0.0
_direct_lock = threading.Lock()


def _direct_allowed():
    return not config.YELP_OPEN_PROXY_COUNTRY and time.monotonic() >= _direct_blocked_until


def _block_direct(reason):
    global _direct_blocked_until
    with _direct_lock:
        if time.monotonic() >= _direct_blocked_until:
            print(f"yelp: direct egress blocked ({reason}); resting it {config.YELP_DIRECT_COOLDOWN}s on residential exits")
        _direct_blocked_until = time.monotonic() + config.YELP_DIRECT_COOLDOWN


class _OpenExit:
    __slots__ = ("proxy", "key", "uses")

    def __init__(self, proxy):
        self.proxy = proxy
        self.key = f"open:{proxy}"
        self.uses = 0


_open_pool = []                 # healthy residential exits shared by every thread
_open_pool_lock = threading.Lock()


def _open_exit(avoid_direct):
    """(session key, proxy) for the next open call: direct while allowed,
    else one of a small shared pool of residential exits (a thread keeps its
    own curl session per exit; the exit IP — and its warmed reputation — is
    shared)."""
    fallback_country = config.YELP_OPEN_PROXY_COUNTRY or config.YELP_OPEN_FALLBACK_PROXY_COUNTRY
    if not fallback_country or (not avoid_direct and _direct_allowed()):
        return "open:direct", None
    with _open_pool_lock:
        for ex in list(_open_pool):
            if ex.uses >= config.YELP_OPEN_REQUESTS_PER_EXIT:
                _open_pool.remove(ex)
        if len(_open_pool) < max(1, config.YELP_OPEN_EXIT_POOL):
            ex = _OpenExit(config.yelp_open_proxy(fallback=not config.YELP_OPEN_PROXY_COUNTRY))
            _open_pool.append(ex)
        else:
            ex = min(_open_pool, key=lambda e: e.uses)
        ex.uses += 1
        return ex.key, ex.proxy


def _retire_open_exit(key):
    with _open_pool_lock:
        for ex in list(_open_pool):
            if ex.key == key:
                _open_pool.remove(ex)
    _drop_session(key)


def _is_ip_block(resp):
    """Yelp's 503 IP-block page, a 429, or Fastly's empty edge 403 (a short
    per-IP limit, often on a fresh shared residential exit). The stale-id
    gql 403 has the body "Forbidden" and is NOT a block."""
    if resp.status_code == 429:
        return True
    text = resp.text or ""
    if resp.status_code == 403 and not text.strip():
        return True
    return resp.status_code in (403, 503) and IP_BLOCK_MARKER in text[:20000]


def _open_request(method, url, **kwargs):
    """One request to an open surface, retried across egresses on IP blocks
    and transport failures. Returns the response of the first attempt that
    was not IP-blocked (any status)."""
    last = None
    for attempt in range(max(1, config.YELP_OPEN_MAX_ATTEMPTS)):
        key, proxy = _open_exit(avoid_direct=attempt > 0)
        try:
            resp = _session(key, proxy).request(method, url, **kwargs)
        except Exception as e:
            if proxy:
                _retire_open_exit(key)
            else:
                _drop_session(key)
            last = YelpUpstreamError(f"request failed: {type(e).__name__}: {e}")
            continue
        if _is_ip_block(resp):
            last = YelpBlocked(f"HTTP {resp.status_code} IP block on {url.split('yelp.com', 1)[-1][:80]}")
            if proxy:
                _retire_open_exit(key)
            else:
                _block_direct(f"HTTP {resp.status_code}")
            continue
        return resp
    raise last


# ---- GraphQL ---------------------------------------------------------------------------

_GQL_HEADERS = {"accept": "*/*", "accept-language": "en-US,en;q=0.9", "content-type": "application/json",
                "origin": SITE, "referer": SITE + "/"}
# One shared pool for the parallel batches of a call: its threads keep their
# curl sessions / sticky exits between calls (a per-call pool would open a
# new TLS tunnel, and on residential egress a new exit, every time).
_GQL_POOL = ThreadPoolExecutor(max(1, config.YELP_GQL_WORKERS) * 4, thread_name_prefix="yelp-gql")
GQL_ATTEMPTS = 2                # per batch, on top of _open_request's egress retries


class _StaleDocId(Exception):
    pass


def _gql_post(ops):
    body = [{"operationName": name, "variables": variables,
             "extensions": {"operationType": "query", "documentId": docids.doc_id(name)}}
            for name, variables in ops]
    resp = _open_request("POST", GQL_URL, json=body, headers=_GQL_HEADERS, timeout=GQL_TIMEOUT)
    text = resp.text or ""
    if resp.status_code == 200:
        try:
            parts = resp.json()
        except ValueError:
            dump_debug("gql_nonjson", text)
            raise YelpUpstreamError("gql answered a non-JSON body")
        if not isinstance(parts, list) or len(parts) != len(ops):
            dump_debug("gql_shape", text)
            raise YelpUpstreamError("gql answered an unexpected shape")
        return parts
    if resp.status_code == 403 and text.strip() == "Forbidden":
        raise _StaleDocId(text)
    if resp.status_code == 400:
        dump_debug("gql_400", text + "\n" + json.dumps(body)[:4000])
        raise YelpBadRequest(f"gql rejected the variables of {[n for n, _ in ops]}")
    if resp.status_code == 403:
        dump_debug("gql_blocked", text)
        raise YelpBlocked(f"gql answered HTTP {resp.status_code}")
    raise YelpUpstreamError(f"gql answered HTTP {resp.status_code}")


def _gql_chunk(ops, healed=False):
    last = None
    for attempt in range(GQL_ATTEMPTS):
        try:
            return _gql_post(ops)
        except _StaleDocId:
            if len(ops) > 1:
                # One stale id fails the whole batch: run the ops one by one so
                # only the stale one pays for the re-mine.
                return [part for op in ops for part in _gql_chunk([op], healed)]
            if healed:
                raise YelpUpstreamError(f"yelp rejected the persisted query {ops[0][0]} "
                                        "(documentId not found after a re-mine)")
            docids.refresh(f"stale documentId for {ops[0][0]}")
            return _gql_chunk(ops, healed=True)
        except YelpBadRequest:
            raise
        except YelpUpstreamError as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last


def gql(ops):
    """Run [(operationName, variables), ...] and return the per-op results
    [{"data": ..., "errors": [...]}, ...] in order (batches of 10, POSTed
    in parallel)."""
    ops = list(ops)
    if not ops:
        return []
    chunks = [ops[i:i + MAX_OPS_PER_BATCH] for i in range(0, len(ops), MAX_OPS_PER_BATCH)]
    if len(chunks) == 1:
        return _gql_chunk(chunks[0])
    parts = list(_GQL_POOL.map(_gql_chunk, chunks))
    return [item for part in parts for item in part]


def gql_one(name, variables):
    return gql([(name, variables)])[0]


def error_codes(result):
    return {((e.get("extensions") or {}).get("code") or "") for e in (result or {}).get("errors") or []
            if isinstance(e, dict)}


def raise_for_input(result, what):
    """A GraphQL result whose root is null because of the input: bad id -> 404,
    bad enum / variable -> 400."""
    codes = error_codes(result)
    messages = "; ".join(str(e.get("message"))[:160] for e in (result or {}).get("errors") or [] if isinstance(e, dict))
    if "BAD_ENCID" in codes or ("BAD_USER_INPUT" in codes and "Variable" not in messages):
        raise YelpNotFound(f"{what} not found on Yelp")
    if "BAD_USER_INPUT" in codes:
        raise YelpBadRequest(messages)
    if codes:
        raise YelpUpstreamError(f"{what}: {messages}")


# ---- DataDome identity -------------------------------------------------------------------

class _Identity:
    _serial = 0
    _serial_lock = threading.Lock()

    def __init__(self, proxy):
        self.proxy = proxy
        self.cookie = None          # datadome cookie value
        self.cookie_gen = 0
        self.uses = 0
        self.solve_lock = threading.Lock()
        with _Identity._serial_lock:
            _Identity._serial += 1
            self.key = f"dd{_Identity._serial}:{proxy or 'direct'}"


class _EdgeLimited(Exception):
    """Fastly's edge answered an empty 403 with retry-after (a short per-IP
    rate limit, not DataDome): back off and retry on the same identity."""


class _Challenge(Exception):
    def __init__(self, captcha_url, hard, gen, status=None, size=0):
        super().__init__(captcha_url or "challenge")
        self.captcha_url = captcha_url
        self.hard = hard
        self.gen = gen
        self.status = status
        self.size = size


_identity = None
_identity_lock = threading.Lock()


def _current_identity():
    global _identity
    with _identity_lock:
        if _identity is None or _identity.uses >= config.YELP_REQUESTS_PER_IDENTITY:
            _identity = _Identity(config.yelp_proxy())
        _identity.uses += 1
        return _identity


def _retire(ident):
    global _identity
    with _identity_lock:
        if _identity is ident:
            _identity = None
    _drop_session(ident.key)


def _page_headers(accept, referer):
    return {
        "user-agent": config.YELP_USER_AGENT,
        "accept": ("application/json" if accept == "json"
                   else "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"),
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": config.YELP_SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "referer": referer or SITE + "/",
    }


def _captcha_url(text, page_url):
    """The captcha / interstitial URL of a DataDome block body: JSON bodies
    carry it as "url"; HTML bodies carry a `var dd={...}` object to build it
    from."""
    body = (text or "").replace("\\/", "/")
    m = CAPTCHA_URL_RE.search(body)
    if m:
        return m.group(0).replace("&amp;", "&")
    m = DD_OBJECT_RE.search(body)
    if not m:
        return None
    try:
        dd = json.loads(m.group(1).replace("'", '"'))
    except ValueError:
        return None
    kind = "interstitial" if dd.get("rt") == "i" else "captcha"
    params = {"initialCid": dd.get("cid"), "hash": dd.get("hsh"), "cid": dd.get("cookie"),
              "t": dd.get("t"), "referer": page_url, "s": dd.get("s"), "e": dd.get("e")}
    return f"https://{dd.get('host') or 'geo.captcha-delivery.com'}/{kind}/?" + urlencode(
        {k: v for k, v in params.items() if v is not None}, quote_via=quote)


def _looks_blocked(text):
    head = (text or "")[:4000]
    return any(m in head for m in DD_MARKERS)


def _gated_once(ident, path, accept, referer):
    url = SITE + path
    gen = ident.cookie_gen
    sess = _session(ident.key, ident.proxy)
    # The solved cookie lives in the thread's cookie JAR (domain .yelp.com):
    # DataDome answers every response with a Set-Cookie datadome, and a
    # per-request cookie next to that jar entry would send two conflicting
    # values. A new solve (cookie_gen bump) overwrites the jar entry.
    if ident.cookie and getattr(sess, "_yelp_cookie_gen", None) != gen:
        sess.cookies.set("datadome", ident.cookie, domain=".yelp.com")
        sess._yelp_cookie_gen = gen
    try:
        resp = sess.get(url, headers=_page_headers(accept, referer), timeout=PAGE_TIMEOUT,
                        allow_redirects=True, http_version=_http11())
    except Exception as e:
        _drop_session(ident.key)
        raise YelpUpstreamError(f"request failed: {type(e).__name__}: {e}")
    text = resp.text or ""
    if resp.status_code == 200 and not _looks_blocked(text):
        if accept == "json":
            try:
                json.loads(text)
            except ValueError:
                raise YelpUpstreamError(f"truncated / non-JSON body for {path} ({len(text)} B)")
        return text, str(resp.url)
    if resp.status_code == 404:
        raise YelpNotFound(f"no Yelp page at {path}")
    if resp.status_code == 400:
        raise YelpBadRequest(f"yelp answered 400 for {path}")
    if resp.status_code in (403, 429) and not text and "retry-after" in {k.lower() for k in resp.headers.keys()}:
        raise _EdgeLimited(f"edge rate limit on {path}")
    if resp.status_code in (403, 405, 429) or _looks_blocked(text):
        captcha = _captcha_url(text, url)
        dump_debug("dd_block", text)
        hard = bool(captcha and re.search(r"[?&]t=bv\b", captcha))
        raise _Challenge(captcha, hard, gen, resp.status_code, len(text))
    raise YelpUpstreamError(f"HTTP {resp.status_code} for {path}")


def _capsolver_solve(ident, captcha_url, website):
    """Mint a datadome cookie through the identity's exit; returns its value."""
    from curl_cffi import requests as curl_requests
    task = {"type": "DatadomeSliderTask", "websiteURL": website, "captchaUrl": captcha_url,
            "userAgent": config.YELP_USER_AGENT, "proxy": ident.proxy}
    payload = {"clientKey": config.CAPSOLVER_API_KEY, "task": task}
    if getattr(config, "CAPSOLVER_APP_ID", None):
        payload["appId"] = config.CAPSOLVER_APP_ID
    started = time.monotonic()
    with curl_requests.Session() as s:
        created = s.post(f"{CAPSOLVER_API}/createTask", json=payload, timeout=30).json()
        task_id = created.get("taskId")
        if not task_id:
            raise YelpBlocked(f"CapSolver refused the DataDome task: "
                              f"{created.get('errorCode')} {created.get('errorDescription')}")
        while time.monotonic() - started < config.YELP_SOLVE_TIMEOUT:
            time.sleep(2)
            result = s.post(f"{CAPSOLVER_API}/getTaskResult",
                            json={"clientKey": config.CAPSOLVER_API_KEY, "taskId": task_id}, timeout=30).json()
            if result.get("status") == "ready":
                cookie = ((result.get("solution") or {}).get("cookie") or "")
                m = re.search(r"datadome=([^;]+)", cookie)
                if not m:
                    raise YelpBlocked("CapSolver solved the DataDome task but returned no cookie")
                print(f"yelp: DataDome solved in {time.monotonic() - started:.1f}s")
                return m.group(1)
            if result.get("errorId"):
                raise YelpBlocked(f"CapSolver failed the DataDome task: "
                                  f"{result.get('errorCode')} {result.get('errorDescription')}")
    raise YelpBlocked("CapSolver DataDome task timed out")


def _probe_captcha(ident):
    """A captcha URL for this identity when a block body carried none (an
    empty 403): the search JSON reliably answers with one."""
    try:
        _gated_once(ident, "/search/snippet?find_desc=pizza&find_loc=San+Francisco%2C+CA", "json", SITE + "/")
    except _Challenge as ch:
        return ch.captcha_url
    except Exception:
        return None
    return None


def _handle_challenge(ident, ch, path):
    """Solve (or wait for a concurrent solve of) the identity's challenge.
    Returns False when the identity must be retired.

    Some paths (/biz/<id>/props) hard-block (t=bv) an identity that has no
    solved cookie yet, while the search JSON answers the same exit with a
    solvable challenge — so an unsolved identity mints its cookie there
    first. A hard block on an already-solved identity retires it."""
    if not config.CAPSOLVER_API_KEY or not ident.proxy:
        return False
    with ident.solve_lock:
        if ident.cookie_gen != ch.gen:
            return True                      # another thread already re-solved it
        captcha = None if ch.hard else ch.captcha_url
        if captcha is None:
            if ch.hard and ident.cookie:
                print(f"yelp: DataDome hard block (t=bv) on {path}")
                return False
            captcha = _probe_captcha(ident)
        if not captcha:
            print(f"yelp: DataDome block without a captcha URL on {path} (HTTP {ch.status}, {ch.size} B)")
            return False
        if re.search(r"[?&]t=bv\b", captcha):
            print(f"yelp: DataDome hard block (t=bv) on {path}")
            return False
        try:
            ident.cookie = _capsolver_solve(ident, captcha, SITE + path)
        except Exception as e:
            print(f"yelp: DataDome solve failed on {ident.key.split('@')[-1]}: {e}")
            return False
        ident.cookie_gen += 1
        return True


def warm_identity():
    """Startup hook: mint the shared DataDome cookie before the first search."""
    gated_get("/search/snippet?find_desc=restaurants&find_loc=San+Francisco%2C+CA", accept="json")


def gated_get(path, accept="json", referer=None):
    """GET a DataDome-gated path (starting with /) and return its text."""
    last = None
    attempts = max(1, config.YELP_IDENTITY_ATTEMPTS)
    limited = 0
    for attempt in range(attempts * 2 + EDGE_LIMIT_RETRIES):   # a solve costs one extra round per exit
        ident = _current_identity()
        try:
            text, _final = _gated_once(ident, path, accept, referer)
            return text
        except _EdgeLimited as e:
            last = YelpBlocked(str(e))
            limited += 1
            if limited > EDGE_LIMIT_RETRIES:
                print(f"yelp: retiring DataDome identity {ident.key.split('@')[-1]} (edge rate limit persists)")
                _retire(ident)
                limited = 0
            else:
                time.sleep(EDGE_LIMIT_BACKOFF * limited)
        except _Challenge as ch:
            last = YelpBlocked(f"DataDome challenge on {path}")
            if not _handle_challenge(ident, ch, path):
                print(f"yelp: retiring DataDome identity {ident.key.split('@')[-1]} after {ident.uses} calls")
                _retire(ident)
                attempts -= 1
                if attempts <= 0:
                    break
        except (YelpNotFound, YelpBadRequest):
            raise
        except YelpUpstreamError as e:
            last = e
            _drop_session(ident.key)
    if config.YELP_BROWSER_FALLBACK:
        return browser_get(path, accept)
    raise last or YelpBlocked(f"DataDome blocked {path}")


# ---- open pages --------------------------------------------------------------------------

def open_get(path, accept="html"):
    """GET an open (server-rendered, cookie-free) path; a DataDome challenge
    moves the call to the gated identity."""
    last = None
    for attempt in range(config.MAX_RETRIES):
        try:
            resp = _open_request("GET", SITE + path, headers=_page_headers(accept, SITE + "/"),
                                 timeout=PAGE_TIMEOUT, allow_redirects=True)
        except YelpBlocked:
            return gated_get(path, accept=accept)      # every open exit blocked: the solved identity
        text = resp.text or ""
        if resp.status_code == 200 and not _looks_blocked(text):
            return text
        if resp.status_code == 404:
            raise YelpNotFound(f"no Yelp page at {path}")
        if resp.status_code in (403, 405) or _looks_blocked(text):
            return gated_get(path, accept=accept)
        last = YelpUpstreamError(f"HTTP {resp.status_code} for {path}")
        time.sleep(config.RETRY_BACKOFF * (attempt + 1))
    raise last


# ---- headful patchright fallback -------------------------------------------------------

_browser = None
_browser_lock = threading.Lock()
_browser_last_use = 0.0
_janitor_started = False


def _browser_janitor():
    global _browser
    while True:
        time.sleep(30)
        with _browser_lock:
            if _browser is not None and time.monotonic() - _browser_last_use > config.YELP_BROWSER_IDLE_SECONDS:
                try:
                    _browser.close()
                except Exception:
                    pass
                _browser = None


def _landing_url(path):
    """The page a real visitor would be on when the site fetches `path`."""
    if path.startswith("/search/snippet"):
        return SITE + "/search" + path[len("/search/snippet"):]
    m = re.match(r"/biz/([^/?#]+)/props", path)
    if m:
        return f"{SITE}/biz/{m.group(1)}"
    return SITE + path


def browser_get(path, accept="json"):
    """In-page fetch from a headful patchright Chrome (fallback only)."""
    global _browser, _browser_last_use, _janitor_started
    from chrome_manager import create_scope
    from patchright_driver import PatchrightDriver

    with _browser_lock:
        if not _janitor_started:
            threading.Thread(target=_browser_janitor, daemon=True, name="yelp-browser-janitor").start()
            _janitor_started = True
        try:
            if _browser is None:
                print("yelp: starting the fallback patchright browser")
                with create_scope():
                    _browser = PatchrightDriver(proxy_url=config.yelp_browser_proxy())
            landing = _landing_url(path)
            page = _browser.nav(landing, referer="https://www.google.com/", mode="blocked",
                                challenge_markers=DD_MARKERS)
            html = page.get("html") or ""
            if _looks_blocked(html):
                raise YelpBlocked(f"DataDome challenged the fallback browser on {path} "
                                  "(set CAPSOLVER_API_KEY to solve it)")
            if accept == "html" and landing == SITE + path:
                return html
            resp = _browser.get(SITE + path, headers={"accept": "application/json" if accept == "json" else "text/html"})
            if resp.status_code == 404:
                raise YelpNotFound(f"no Yelp page at {path}")
            if not resp.ok or _looks_blocked(resp.text):
                raise YelpBlocked(f"DataDome challenged the fallback browser on {path}"
                                  + (" (search pages past the first need CAPSOLVER_API_KEY)" if "start=" in path else ""))
            return resp.text
        except (YelpBlocked, YelpNotFound):
            raise
        except Exception as e:
            try:
                if _browser is not None:
                    _browser.close()
            except Exception:
                pass
            _browser = None
            raise YelpUpstreamError(f"fallback browser failed: {type(e).__name__}: {e}")
        finally:
            _browser_last_use = time.monotonic()
