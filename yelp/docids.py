"""Persisted-query ids for www.yelp.com/gql/batch, and their re-miner.

/gql/batch only runs PERSISTED queries: each op is sent as
{operationName, variables, extensions: {operationType, documentId}} where
documentId is a 64-hex hash of the query text. Raw query text is refused,
and so is an id the server no longer knows — a bare 9-byte 403 "Forbidden"
from envoy that fails the whole batch.

The ids live in the site's own JS. Every page ships a webpack runtime
(module_yelp-frontend_runtime~<app>.yji-<hash>.mjs) whose chunk-filename
function names every lazy chunk of that app, either as explicit literals
(`12345===e?"module_…mjs"`) or as a pair of maps
(`({id:"name"})[e]+".yji-"+({id:"hash"})[e]+".chunk.mjs"`). Each chunk
declares its queries as tagged templates:

    Object.assign(gql`${fragment} query GetBusinessReviewFeed(…) {…}`,
                  {__documentId:"2b29fe44…"})

refresh() walks those runtimes for five pages — a user profile and a
business Q&A page (open, plain curl), and the business, business-photos and
search pages (behind DataDome, fetched through fetch.gated_get) — downloads
every chunk from the open CDN (~500 files, ~15 MB) and rebuilds the table. It runs when a call
answers the stale-id 403, at most once per config.YELP_DOCIDS_REFRESH_INTERVAL,
and persists the result to config.YELP_DOCIDS_FILE so a restart keeps it.

The defaults below were mined 2026-09-26 and verified live.
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

CDN = "https://s3-media0.fl.yelpcdn.com/assets/public/"

DEFAULT_DOC_IDS = {
    # business identity / details
    "GetBizPhotosPageData": "ea290485a8a348a414d3651f50446d01da8f3b482a38f04551eb05d162214f37",
    "GetBizHeaderData": "5b3701df4dd3a2d897caae5a8a92971d1f29cb836e7f46d947e1b22968c6d19e",
    "GetLocalBusinessJsonLinkedData": "ca2f5298f309b1d2d64943195986eb3c9aa7b9763c5e34450a09ce77e4191e04",
    "GetBusinessHours": "3a647e54dc8a46dfe3992682c5cc4d184e3731cdf2ecd9a2e24d6bc03c2fbb35",
    "GetSpecialHoursAlert": "a49de4a991ddf7f57b7eca7815a43a51ed61a0d783b9b53b48ae3b2cb1489186",
    "GetBizContactInfo": "71316e8bd099554db0619dd82e7d8876af7a0550d94488cf15a01123b2acc0c5",
    "GetBizPageProperties": "29e65e179910db90c244950c0c7aa389f81c195bcd4009e8fdd15f9bc8d7e4da",
    "GetBusinessHealthScoreAlert": "4f90ef40c6943b34edee3eac4ea4451f79049c331a78b23d537c13d23bed7401",
    "GetFromTheBusiness": "367dc08bd75272c0bdd4d912aaffc6bafb754a38b881f3f9fbe414009d4b3d08",
    "GetBusinessOnTheMenuPopularXData": "637f47e1ebb9d08c79b7ae5a22bac2d1f9df80dc5fd81837aaf3800b4ea8043d",
    "GetBusinessClaimability": "6b7fa4a41d203c44429f854f8b57ce25f0ed61f765e1db7c04c30b5593239f74",
    "GetNotRecommendedReviewsProps": "1d6b1ca748ba8b7fb5bff2396255babeba8951d7a8d0c1ea72e9d825fe0b3cd4",
    "GetBizDetailsMetaHead": "d1861e92665cc334259b63c1aa24e3110b57f1c9d9b890ae2f18c21af07bb1d3",
    "GetVibeCheckData": "b57bd656d95bd035cafecb5c686fae5efea9e912278087ea2f72cc0e2d1c7225",
    "getCategoryBreadcrumbsJsonLinkedData": "10ad42b0b2ab2888cb23b398111c3e647f1f6e6d39a43cedc89a3fcd7ddd25f5",
    "GetMapBoxV2Data": "f58488d7a24d26a433a38d6797932b441c001ca0aafca191a47a3f5105bfc997",
    "GetTransactionSectionData": "2f9fafd7eaef591775d749e64183748bc3dc2159161ba4939e7de2e1ccef7e6b",
    "GetPhotoHeaderDataWithMetadata": "df5d4ed63bbd76062e68d7ae19a13f0ac9fe4f95dc51e83f3b6971012c6dd2b1",
    "GetReviewSummary": "37a92ecad6092164a19f434984913a750d45ef02e6021798b6d8b3f5fe8f83e2",
    "GetCategoriesAndJobs": "2182cb18988271e445cb2bd2ea32961cb952c76623609011215da09654d88c5e",
    "GetBizConsumerAlertsHistory": "4d7c626c03ecfc692ae12683883a63d6fde95417be0e0f9298c17a0ba5c991a5",
    "GetIsOnlineBusiness": "bc5eba2dc84ac87a8cc0e7d0b8c32df3bfb4c07510c42f8be27ee297c95bd4cd",
    "GetVerifiedLicenseData": "0be913fb52b79279a046af71b0507ce525031ad9ab30a3d9cf247bfcda54733d",
    # reviews / photos / dishes / Q&A / posts
    "GetReviewTopics": "830b474ac23e81d07f56a7ccdfa528017de69e6ff4664ebfc482eb0b7e8ef7a5",
    "GetBusinessReviewFeed": "2b29fe4414313b319cb85e119740e72da582d64ad2962841724748be23d7f692",
    "GetFilteredReviews": "c9101a030608f447a20268fae6d93c6efc26f925c438257e84171583acb80892",
    "GetReviewHighlightsWithPopX": "47ec4def7b03953313ee8382f7454f8b40ca6a8027af4c338c25ec6a45d3de3d",
    "GetBizPhotosMediaGrid": "b93f67a6adda64e29ddca97687eddb13ce6bb889922c1243bafc38d6fd5118fc",
    "GetLightboxData": "d59ed373f0ab6c97c640cd8f1c1a7a48f98608560f58904f5d45476a7d599b12",
    "GetPopularXMentions": "6e4b7c9a26aaa878d1bbdeecbd16eefa284cc373efde404ea4aee245def590f3",
    "GetBizQuestionsOverviewContentData": "b65b52503d7943eb3374190331513ecf0e1b63a2b1977bfec6e612fa06eaa094",
    "GetQuestionDetailsContentData": "3c846406858692ef31a860b8d8c58a2eb3d8c303f2eacd2f4bca283de0177eeb",
    "GetBusinessPosts": "eade0e1efc05bd03c42a88d40b7914aeb9d2d81ea9e4de03ee8c6c2329247e4a",
    # batch lookups / search / autocomplete
    "GetStructuredBusinessListData": "3189bd21a0b5d15ac65883a22679abfe5d66418eae8660b0c11496f2325dcb36",
    "GetResultsSectionData": "909fa212ea821a65ff6d960e582713664117bfae8dd09db8a588fe691a0e5d76",
    "GetMapData": "98df21437b5529a0a207ec71e04716f0dc8cdaa3dd9eefd595c2319f0e90fe63",
    "GetCommunityAnswerBusinessSearch": "fb2bf7f6dc22a11a967c431e63a9e80d47aebb8ac2ee587e54eb170a6e448581",
    "GetSuggestions": "8543686314472d18bee98d2ad20e165e9fb31ff695d513cfc48df5e4a5a6a422",
    "GetLocationSuggestions": "4c96bff880e6ec39de51a239e249bebd082c4e9eb8e465b14ec461118cabb90a",
    # users
    "GetUserProfilePageData": "326275eceb46d3c49158e0a3052875c152e0f336ae2eb4b8675f4614a28fcec2",
    "GetProfileOverviewAboutData": "79e643b54caa9bb87e301050de560f0538c9d896ddfd82f50337beebb90904d1",
    "GetProfileOverviewImpactData": "d565847844e4b42f14348d588885a0486d60c19c948962dfc82c1ca133549c64",
    "GetProfileYearsEliteContentData": "e5041918fcc24438ae55aa0dce0b413aa44cf8075e4fdc24445c1e7e71878b27",
    "GetProfileReviewsContentData": "fca03ef172c3809e5440089b14c30973b58b117d96fdab9fe8fd61be28a5faf2",
    "GetProfilePhotosMediaGrid": "2f50fb7cd3e8840cb043d0f7533d66d5fcd9a8a792624e022989a024f90e2294",
    "GetUserFriendsData": "7e0a2fa5d7fbd2f3d87be80591228bb94cbf9e24d1aa146785ee24d46e913854",
    "GetUserFollowingData": "192baae9cfa0c01afd03ce5570706864e29610ffcb91dcc876d114b463a9e970",
    "GetProfileComplimentsContentData": "d2cd98849927cfb0aec31e357eefdeb423766d655014ce8a3cf6e42d4cf8d52d",
}

_lock = threading.Lock()
_refresh_lock = threading.Lock()
_ids = dict(DEFAULT_DOC_IDS)
_last_refresh = 0.0


def _load_persisted():
    try:
        with open(config.YELP_DOCIDS_FILE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return
    if isinstance(saved, dict):
        _ids.update({k: v for k, v in saved.items()
                     if k in DEFAULT_DOC_IDS and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)})


_load_persisted()


def doc_id(name):
    with _lock:
        return _ids[name]


# ---- mining ------------------------------------------------------------------------

_OP_RE = re.compile(r'`([^`]*?\b(?:query|mutation)\s+(\w+)[^`]*)`\s*,\s*\{\s*__documentId\s*:\s*"([0-9a-f]{64})"', re.S)
_MODULE_RE = re.compile(r'https://s3-media0\.fl\.yelpcdn\.com/assets/public/[^"\'\s]+?\.mjs')
_MAP_RE = re.compile(r'\{((?:\d+:"[^"]*",?)+)\}')
_HASH16 = re.compile(r"[0-9a-f]{16}")


def runtime_chunks(text):
    """Every chunk filename a webpack runtime can load: explicit literals
    plus the ({id: name})[e] + mid + ({id: hash})[e] + suffix templates."""
    out = {c for c in re.findall(r'"([\w.~-]+\.mjs)"', text) if not c.startswith(".")}
    maps = [(m.start(), m.end(), dict(re.findall(r'(\d+):"([^"]*)"', m.group(1)))) for m in _MAP_RE.finditer(text)]
    for (s1, e1, names), (s2, e2, hashes) in zip(maps, maps[1:]):
        if not hashes or not all(_HASH16.fullmatch(h) for h in hashes.values()):
            continue
        if any(_HASH16.fullmatch(v) for v in names.values()):
            continue
        mid = re.search(r'\+"([^"]*)"\+', text[e1:s2])
        suffix = re.match(r'\)\[\w\]\+"([^"]*)"', text[e2:e2 + 80])
        prefix = re.search(r'"([^"]*)"\+\(*$', text[max(0, s1 - 60):s1])
        if not (mid and suffix and suffix.group(1).endswith(".mjs")):
            continue
        for key, name in names.items():
            if key in hashes:
                out.add(f"{prefix.group(1) if prefix else ''}{name}{mid.group(1)}{hashes[key]}{suffix.group(1)}")
    return out


def _chunk_url(name):
    if name.startswith("module_") or name.endswith(".chunk.mjs"):
        return CDN + name
    return CDN + "module_" + name


def ops_in(text):
    """{operationName: documentId} for every persisted query in a JS text."""
    return {name: did for _full, name, did in _OP_RE.findall(text or "")}


def _get_text(session, url):
    try:
        resp = session.get(url, timeout=30)
        return resp.text if resp.status_code == 200 else ""
    except Exception:
        return ""


def mine(page_htmls):
    """{op: documentId} mined from the pages' modules and runtimes."""
    from curl_cffi import requests as curl_requests
    session = curl_requests.Session(impersonate="chrome")
    modules = set()
    for html in page_htmls:
        modules |= set(_MODULE_RE.findall(html or ""))
    urls = set(modules)
    for runtime in [m for m in modules if "runtime~" in m]:
        urls |= {_chunk_url(c) for c in runtime_chunks(_get_text(session, runtime))}
    found = {}
    with ThreadPoolExecutor(16) as pool:
        for text in pool.map(lambda u: _get_text(session, u), sorted(urls)):
            found.update(ops_in(text))
    session.close()
    return found


def refresh(reason=""):
    """Re-mine the ids (at most once per YELP_DOCIDS_REFRESH_INTERVAL).
    Returns the names whose id changed."""
    global _last_refresh
    with _refresh_lock:
        if time.monotonic() - _last_refresh < config.YELP_DOCIDS_REFRESH_INTERVAL and _last_refresh:
            return set()
        _last_refresh = time.monotonic()
        from yelp import fetch
        print(f"yelp: re-mining gql documentIds ({reason})")
        pages = []
        for path in (f"/user_details?userid={config.YELP_SEED_USER}",
                     f"/questions/{config.YELP_SEED_BUSINESS}"):
            try:
                pages.append(fetch.open_get(path))
            except Exception as e:
                print(f"yelp: docid miner could not load {path}: {e}")
        # DataDome-gated apps: business page, photos page, search page.
        for path in (f"/biz/{config.YELP_SEED_BUSINESS}", f"/biz_photos/{config.YELP_SEED_BUSINESS}",
                     "/search?find_desc=pizza&find_loc=San+Francisco%2C+CA"):
            try:
                pages.append(fetch.gated_get(path, accept="html"))
            except Exception as e:
                print(f"yelp: docid miner could not load {path}: {e}")
        found = mine(pages)
        changed = set()
        with _lock:
            for name in DEFAULT_DOC_IDS:
                if found.get(name) and found[name] != _ids.get(name):
                    _ids[name] = found[name]
                    changed.add(name)
            snapshot = dict(_ids)
        if changed:
            try:
                with open(config.YELP_DOCIDS_FILE, "w") as f:
                    json.dump(snapshot, f)
            except OSError:
                pass
        missing = [n for n in DEFAULT_DOC_IDS if n not in found]
        print(f"yelp: documentId re-mine found {len(found)} ops, changed {sorted(changed) or 'none'}"
              + (f", not found {missing}" if missing else ""))
        return changed


if __name__ == "__main__":
    print(json.dumps(sorted(refresh("manual run")), indent=1))
