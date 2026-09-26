"""Yelp response parsers: raw GraphQL / page JSON / HTML -> the public shapes.
Pure functions (no network), tolerant of partial responses: every read goes
through shared.dig / .get with a None default.

Conventions: snake_case keys; `link` for URLs; booleans as is_/has_ questions;
identity keys first, then content, stats, nested objects, metadata last;
timestamps as ISO-8601 UTC ('2026-08-17T22:17:33Z'), calendar dates as
'YYYY-MM-DD'; money as numeric amount + `currency`; missing = null.

Dropped on purpose (noise): __typename, csrf tokens, ad logging / tracking
ids, UI format blocks (assetFormat, colours, icon names), logged-in-user
fields (always null logged-out), static map image URLs (they embed Yelp's
Google Maps key), duplicate photo sizes (one original + one thumbnail kept).
"""
import html as html_lib
import json
import re

from yelp.shared import (SITE, absolute, as_list, biz_link, dig, edges, elite_year, highlight_text, iso_date,
                         local_date, money, num, paragraphs, photo, photo_link, price_level, strip_tags, text,
                         to_int, us_date, user_link, utc_datetime)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_SHORT_DAYS = {d[:3]: d for d in WEEKDAYS}


# ---- small shared objects -------------------------------------------------------------

def categories(raw):
    out = []
    for c in as_list(raw):
        if not isinstance(c, dict):
            continue
        alias = c.get("alias")
        out.append({"alias": alias, "title": text(c.get("title")),
                    "root_alias": dig(c, "root", "alias")})
    return out


def merge_categories(*lists):
    """Categories from several ops (some carry the alias, some only the title)."""
    by_title = {}
    for lst in lists:
        for c in lst:
            key = c.get("title") or c.get("alias")
            cur = by_title.setdefault(key, dict(c))
            for k, v in c.items():
                if cur.get(k) is None and v is not None:
                    cur[k] = v
    return list(by_title.values())


def address(raw_address, country_code=None, formatted=None):
    a = raw_address or {}
    lines = [text(a.get(k)) for k in ("addressLine1", "addressLine2", "addressLine3")]
    out = {
        "line1": lines[0], "line2": lines[1], "line3": lines[2],
        "city": text(a.get("city")), "state": text(a.get("regionCode")),
        "postal_code": text(a.get("postalCode")), "country_code": country_code,
        "formatted": text((formatted or a.get("formatted") or "").replace("\n", ", ")) or None,
    }
    if out["formatted"] and not (out["state"] and out["postal_code"]):
        # "…, San Francisco, CA 94133" (US / CA-style last line) fills the
        # state / postal code the list ops leave out.
        m = re.search(r"(?:^|,\s*)([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?|[A-Z]\d[A-Z]\s?\d[A-Z]\d)$", out["formatted"])
        if m:
            out["city"] = out["city"] or text(m.group(1))
            out["state"] = out["state"] or m.group(2)
            out["postal_code"] = out["postal_code"] or m.group(3)
    if not out["formatted"]:
        parts = [p for p in (out["line1"], out["line2"], out["line3"]) if p]
        tail = " ".join(p for p in (out["state"], out["postal_code"]) if p)
        city = ", ".join(p for p in (out["city"], tail) if p)
        out["formatted"] = ", ".join(parts + ([city] if city else [])) or None
    return out


def coordinates(raw):
    lat, lng = num(dig(raw, "latitude")), num(dig(raw, "longitude"))
    return {"latitude": lat, "longitude": lng} if lat is not None and lng is not None else None


def author(raw):
    """A reviewer / uploader / answerer ("user passport")."""
    if not isinstance(raw, dict) or not raw.get("encid"):
        return None
    photo_url = (dig(raw, "profilePhoto", "photoUrl", "url") or dig(raw, "profilePhoto", "photoUrl", "userSrc")
                 or dig(raw, "profilePhoto", "photoUrl", "url1x"))
    year = elite_year(raw.get("currentTruncatedEliteYear"))
    return {
        "id": raw.get("encid"),
        "name": text(raw.get("displayName")),
        "link": user_link(raw.get("encid")),
        "location": text(raw.get("displayLocation")),
        "photo_link": photo_link(photo_url, "o") if photo_url and "default_user_avatar" not in photo_url else None,
        "review_count": to_int(raw.get("reviewCount")),
        "friend_count": to_int(raw.get("friendCount")),
        "photo_count": to_int(raw.get("businessPhotoCount")),
        "elite_year": year,
        "is_elite": year is not None if "currentTruncatedEliteYear" in raw else None,
        "is_elite_all_star": bool(raw.get("isEliteAllStar")) if raw.get("isEliteAllStar") is not None else None,
    }


def media_photo(node):
    """A business photo node (media grid / lightbox / review photos)."""
    if not isinstance(node, dict):
        return None
    url = (dig(node, "viewerPhotoUrl", "url") or dig(node, "photoUrl", "url") or dig(node, "photoUrl", "contentUrl")
           or dig(node, "thumbnailPhotoUrl", "url348") or dig(node, "photoUrl", "thumbnail"))
    uploader = node.get("uploadingUser")
    likes = None
    for r in as_list(dig(node, "availableReactionsContainer", "availableReactions")):
        if isinstance(r, dict) and r.get("reactionType") == "PHOTO_LIKE":
            likes = to_int(r.get("count"))
    meta = node.get("metadata") or {}
    out = photo(
        encid=node.get("encid"), url=url, caption=node.get("caption"), width=node.get("width"),
        height=node.get("height"),
        uploaded_at=dig(node, "createdAt", "utcDateTime") or dig(meta, "uploadDate", "utcDateTime") or dig(node, "timeUploaded", "utcDateTime"),
    )
    if out is None:
        return None
    tags = []
    for k in as_list(meta.get("keywords")):
        k = text(k)
        if k and k not in tags:
            tags.append(k)
    out["tags"] = tags or None
    out["like_count"] = likes
    out["uploaded_by"] = author(uploader) if isinstance(uploader, dict) and uploader.get("encid") else (
        {"name": text(meta.get("author"))} if meta.get("author") else None)
    return out


def video(node):
    if not isinstance(node, dict):
        return None
    duration = None
    for r in as_list(dig(node, "videoPublication", "renditionSet")):
        if isinstance(r, dict) and r.get("duration"):
            duration = round(to_int(r.get("duration")) / 1000, 1)
            break
    return {"id": node.get("encid"), "link": node.get("videoUrl"), "thumbnail_link": node.get("thumbnailUrl"),
            "caption": text(node.get("caption")), "duration_seconds": duration,
            "uploaded_at": utc_datetime(dig(node, "createdAt", "utcDateTime")),
            "uploaded_by": author(node.get("uploadingUser"))}


# ---- hours ---------------------------------------------------------------------------------

def _clock(minutes):
    minutes = minutes % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def weekly_hours(week):
    """regularHoursMergedWithSpecialHoursForCurrentWeek -> [{day, hours, ranges}].
    regularHoursRaw holds [open, close] minutes from Monday 00:00."""
    out = []
    for i, day in enumerate(as_list(week)):
        if not isinstance(day, dict):
            continue
        name = _SHORT_DAYS.get(day.get("dayOfWeekShort")) or day.get("dayOfWeek") or (WEEKDAYS[i] if i < 7 else None)
        ranges = []
        for pair in as_list(day.get("regularHoursRaw")):
            if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, int) for x in pair):
                start, end = pair
                ranges.append({"open": _clock(start), "close": _clock(end),
                               "is_overnight": end // 1440 != start // 1440 and end % 1440 != 0})
        # GetBusinessHours days carry `hours`; the JSON-LD op's days (the
        # fallback when GetBusinessHours fails) carry only `regularHours`.
        raw_hours = day.get("hours") if day.get("hours") is not None else day.get("regularHours")
        hours = [text(h) for h in as_list(raw_hours) if text(h)]
        out.append({"day": name, "hours": hours, "is_closed": not hours or hours == ["Closed"],
                    "has_special_hours": bool(day.get("hasSpecialHours")), "ranges": ranges or None})
    return out


def special_hours(raw):
    out = []
    for s in as_list(raw):
        if not isinstance(s, dict):
            continue
        out.append({"date": iso_date(s.get("date")), "hours": [text(h) for h in as_list(s.get("hours")) if text(h)] or None,
                    "is_closed": s.get("isClosed")})
    return out


# ---- business details ------------------------------------------------------------------------

_ATTRIBUTE_NAMES = {
    # yelp alias -> public key (duplicate lower-case aliases are folded away)
    "BusinessAcceptsCreditCards": "accepts_credit_cards", "BusinessAcceptsApplePay": "accepts_apple_pay",
    "BusinessAcceptsAndroidPay": "accepts_google_pay", "BusinessAcceptsBitcoin": "accepts_cryptocurrency",
    "BusinessParking": "parking", "WheelchairAccessible": "is_wheelchair_accessible",
    "GenderNeutralRestrooms": "has_gender_neutral_restrooms", "OutdoorSeating": "has_outdoor_seating",
    "HasPoolTable": "has_pool_table", "ByAppointmentOnly": "is_by_appointment_only", "Caters": "offers_catering",
    "offers_contactless_delivery": "offers_contactless_delivery", "offers_military_discount": "offers_military_discount",
    "DogsAllowed": "allows_dogs", "AcceptsInsurance": "accepts_insurance", "Corkage": "charges_corkage",
    "BYOBCorkage": "byob", "RestaurantsPriceRange2": "price_level", "WiFi": "wifi", "Alcohol": "alcohol",
    "NoiseLevel": "noise_level", "RestaurantsAttire": "attire", "Ambience": "ambience", "GoodForMeal": "good_for_meals",
    "BestNights": "best_nights", "Music": "music", "Smoking": "smoking", "HappyHour": "has_happy_hour",
    "RestaurantsGoodForGroups": "is_good_for_groups", "GoodForKids": "is_good_for_kids",
    "RestaurantsTakeOut": "offers_takeout", "RestaurantsDelivery": "offers_delivery",
    "RestaurantsReservations": "takes_reservations", "RestaurantsTableService": "has_table_service",
    "HasTV": "has_tv", "BikeParking": "has_bike_parking", "DriveThru": "has_drive_thru",
    "GoodForDancing": "is_good_for_dancing", "CoatCheck": "has_coat_check", "Open24Hours": "is_open_24_hours",
    "AgesAllowed": "ages_allowed", "DietaryRestrictions": "dietary_restrictions",
}
_ATTRIBUTE_FALLBACKS = {"accepts_credit_cards": "BusinessAcceptsCreditCards", "accepts_apple_pay": "BusinessAcceptsApplePay",
                        "accepts_android_pay": "BusinessAcceptsAndroidPay", "accepts_bitcoin": "BusinessAcceptsBitcoin",
                        "is_wheelchair_accessible": "WheelchairAccessible", "by_appointment_only": "ByAppointmentOnly",
                        "caters": "Caters", "accepts_insurance": "AcceptsInsurance"}


def attributes(raw):
    """businessAttributesByAliases -> {public_name: bool | str | [str]}; attributes
    Yelp has no value for are left out rather than reported as false."""
    out = {}
    for a in as_list(raw):
        if not isinstance(a, dict):
            continue
        alias = a.get("alias")
        alias = _ATTRIBUTE_FALLBACKS.get(alias, alias)
        key = _ATTRIBUTE_NAMES.get(alias)
        if not key:
            continue
        if a.get("boolValue") is not None:
            value = bool(a["boolValue"])
        elif isinstance(a.get("multiValue"), list):
            value = [v.get("alias") for v in a["multiValue"] if isinstance(v, dict) and v.get("alias")]
        elif isinstance(a.get("singleValue"), dict):
            value = a["singleValue"].get("alias")
            if key == "price_level":
                value = to_int(value)
        else:
            continue
        if value is None or key in out:
            continue
        out[key] = value
    return out


def amenities(page_properties):
    out = []
    for group in as_list(dig(page_properties, "organizedProperties")):
        for p in as_list(dig(group, "properties")):
            if isinstance(p, dict) and p.get("displayText"):
                out.append({"alias": p.get("alias"), "name": text(p.get("displayText")),
                            "is_available": bool(p.get("isActive"))})
    return out


def health_inspections(raw):
    out = []
    for h in as_list(raw):
        if not isinstance(h, dict):
            continue
        out.append({
            "score": text(h.get("formattedScore")), "date": iso_date(h.get("dateTime")),
            "violations": [text(v.get("description")) for v in as_list(h.get("violations")) if isinstance(v, dict) and text(v.get("description"))],
            "provider": {"name": text(dig(h, "provider", "displayName")), "link": dig(h, "provider", "url")} if h.get("provider") else None,
            "is_estimated": bool(dig(h, "provider", "isEstimatedHealthScore")),
        })
    return out


def licenses(raw):
    out = []
    for lic in as_list(raw):
        if not isinstance(lic, dict):
            continue
        out.append({"number": text(lic.get("licenseNumber")), "trade": text(lic.get("trade")),
                    "issued_by": text(lic.get("issuingAuthority") or lic.get("issuedBy")),
                    "licensee": text(lic.get("licensee")),
                    "verified_on": iso_date(lic.get("verificationDate") or lic.get("verifiedDate")),
                    "expires_on": iso_date(lic.get("expiryDate"))})
    return out


def services(categories_and_jobs):
    """Services a (home / local services) business says it offers, with the
    items it works on, grouped per category job."""
    out = []
    for cat in as_list(dig(categories_and_jobs, "categories")):
        for job in as_list(dig(cat, "currentBusinessJobs")):
            for child in as_list(dig(job, "childJobs")):
                if not isinstance(child, dict):
                    continue
                details = []
                for group in as_list(child.get("groupedJobAttributes")):
                    for attr in as_list(dig(group, "attributes")):
                        if isinstance(attr, dict) and attr.get("isOffered"):
                            details.append(text(attr.get("displayName")))
                out.append({"alias": child.get("alias"), "name": text(child.get("canonicalDisplayName")),
                            "category_alias": cat.get("alias"), "is_offered": bool(child.get("isOffered")),
                            "details": [d for d in details if d] or None})
    return out


def portfolio(raw):
    out = []
    for node in edges(dig(raw, "projectsConnection")):
        photos = [photo(encid=p.get("encid"), url=dig(p, "photoUrl", "url"), caption=p.get("caption"))
                  for p in edges(node.get("photosConnection"))]
        out.append({"id": node.get("encid"), "name": text(node.get("name")) or text(dig(node, "coverPhoto", "caption")),
                    "photos": [p for p in photos if p]})
    return out


def popular_dishes(popular_x):
    out = []
    for e in as_list(dig(popular_x, "carousel", "entities")):
        if not isinstance(e, dict):
            continue
        price, currency = money(e.get("priceString"))
        pp = e.get("primaryPhoto") or {}
        out.append({
            "id": e.get("identifier"), "name": text(e.get("displayName")),
            "photo": photo(encid=pp.get("encid"), url=dig(pp, "photoUrl", "url"), caption=pp.get("caption"),
                           uploaded_at=dig(pp, "metadata", "uploadDate", "utcDateTime")) if pp else None,
            "price": price, "currency": currency if price is not None else None,
            "rating": round(num(e.get("meanRating")), 2) if num(e.get("meanRating")) is not None else None,
            "review_count": to_int(e.get("reviewCount")), "photo_count": to_int(e.get("photoCount")),
        })
    return out


def rating_distribution(counts):
    """reviewCountsByRating [1-star .. 5-star] -> {"1": n, ..., "5": n}."""
    counts = as_list(counts)
    if len(counts) != 5:
        return None
    return {str(i + 1): to_int(c) for i, c in enumerate(counts)}


def language_counts(raw):
    return [{"language": x.get("language"), "count": to_int(x.get("count"))}
            for x in as_list(raw) if isinstance(x, dict) and x.get("language")] or None


def details(res, alias_or_id):
    """res = {operationName: data} of the business-details fan-out."""
    header = dig(res, "GetBizHeaderData", "business") or {}
    ld = dig(res, "GetLocalBusinessJsonLinkedData", "business") or {}
    hours = dig(res, "GetBusinessHours", "business") or {}
    special = dig(res, "GetSpecialHoursAlert", "business") or {}
    contact = dig(res, "GetBizContactInfo", "business") or {}
    props = dig(res, "GetBizPageProperties", "business") or {}
    health = dig(res, "GetBusinessHealthScoreAlert", "business") or {}
    about = dig(res, "GetFromTheBusiness", "business") or {}
    menu_data = dig(res, "GetBusinessOnTheMenuPopularXData") or {}
    menu_biz = menu_data.get("business") or {}
    claim = dig(res, "GetBusinessClaimability", "business", "claimability") or dig(header, "claimability") or {}
    not_rec = dig(res, "GetNotRecommendedReviewsProps", "business") or {}
    meta = dig(res, "GetBizDetailsMetaHead", "seoMetadata", "bizDetails") or {}
    vibe = dig(res, "GetVibeCheckData", "business", "ambiance") or {}
    lic = dig(res, "GetVerifiedLicenseData", "business", "verifiedLicenses")
    crumbs = dig(res, "getCategoryBreadcrumbsJsonLinkedData", "business", "categories") or []
    mapbox = dig(res, "GetMapBoxV2Data", "business") or {}
    txn = (as_list(dig(res, "GetTransactionSectionData", "businesses")) or [{}])[0] or {}
    photo_header = dig(res, "GetPhotoHeaderDataWithMetadata", "business") or {}
    summary = dig(res, "GetReviewSummary", "business") or {}
    jobs = dig(res, "GetCategoriesAndJobs", "business") or {}
    alerts = dig(res, "GetBizConsumerAlertsHistory", "business", "historicalConsumerAlerts")
    online = dig(res, "GetIsOnlineBusiness", "business", "isOnlineBusiness")

    alias = ld.get("alias") or contact.get("alias") or menu_biz.get("alias") or alias_or_id
    location = ld.get("location") or {}
    country = dig(location, "country", "code") or dig(header, "location", "country", "code")
    ancestry = {}
    for c in crumbs:
        chain = [text(a.get("title")) for a in as_list(c.get("ancestry")) if isinstance(a, dict)]
        if c.get("encid") and chain:
            ancestry[c["encid"]] = chain
    cats = []
    raw_cats = as_list(ld.get("categories")) or as_list(header.get("categories"))
    for c in raw_cats:
        if isinstance(c, dict):
            cats.append({"alias": c.get("alias"), "title": text(c.get("title")), "root_alias": dig(c, "root", "alias"),
                         "path": ancestry.get(c.get("encid"))})
    website = dig(contact, "externalResources", "website") or dig(menu_biz, "externalResources", "website") or {}
    menu_ext = dig(menu_biz, "externalResources", "menu", "url")
    menu_yelp = dig(menu_biz, "yelpMenu", "url")
    responsive = dig(menu_biz, "messaging", "responsiveness") or {}
    today = dig(hours, "operationHours", "regularHoursMergedWithSpecialHoursForCurrentDay") or \
        dig(header, "operationHours", "regularHoursMergedWithSpecialHoursForCurrentDay") or {}
    owner = about.get("bizOwnerProfile") or {}
    primary = ld.get("primaryPhoto") or {}
    exterior = mapbox.get("exteriorPhoto") or {}
    media = dig(photo_header, "media", "orderedMediaItems") or {}
    service_area = dig(contact, "serviceArea", "areas") or dig(mapbox, "serviceArea", "areas")
    price_display = dig(ld, "priceRange", "display") or dig(header, "priceRange", "display")
    history = about.get("history") or {}
    consumer_alert = health.get("consumerAlert") or {}
    year = to_int(history.get("yearEstablished"))

    return {
        "id": ld.get("encid") or header.get("encid"),
        "alias": alias,
        "name": text(ld.get("name") or header.get("name")),
        "link": biz_link(alias),
        "alternate_names": [text(n) for n in as_list(header.get("alternateNames")) if text(n)] or None,
        "summary": text(dig(header, "summary", "text")),
        "rating": num(ld.get("rating") if ld.get("rating") is not None else header.get("rating")),
        "review_count": to_int(ld.get("reviewCount") if ld.get("reviewCount") is not None else header.get("reviewCount")),
        "not_recommended_review_count": to_int(not_rec.get("notRecommendedReviewCount")),
        "rating_distribution": rating_distribution(summary.get("reviewCountsByRating")),
        "photo_count": to_int(media.get("totalCount")),
        "price_range": price_display,
        "price_level": price_level(price_display),
        "categories": cats,
        "phone": text(dig(contact, "phoneNumber", "formatted") or dig(ld, "phoneNumber", "formatted")),
        "tracked_phone": text(dig(contact, "meteredPhoneNumber", "phoneText")),
        "website": {"link": website.get("url"), "display_link": website.get("displayUrl"),
                    "is_verified": website.get("isTrusted")} if website.get("url") else None,
        "address": address(location.get("address"), country, dig(contact, "location", "address", "formatted")),
        "neighborhoods": [text(n) for n in as_list(dig(mapbox, "location", "neighborhoods")) if text(n)] or None,
        "coordinates": coordinates(location.get("geoCoordinate")),
        "timezone": dig(special, "location", "timezone") or dig(txn, "operationHours", "timezone"),
        "service_area": [text(a) for a in as_list(service_area) if text(a)] or None,
        "hours": {
            "is_open_now": today.get("isCurrentlyOpen"),
            "today": [text(h) for h in as_list(today.get("hours")) if text(h)] or None,
            "weekly": weekly_hours(dig(hours, "operationHours", "regularHoursMergedWithSpecialHoursForCurrentWeek")
                                   or dig(ld, "operationHours", "regularHoursMergedWithSpecialHoursForCurrentWeek")),
            "special": special_hours(dig(hours, "operationHours", "upcomingSpecialHours")) or None,
            "holidays": [{"name": text(h.get("name")), "date": iso_date(h.get("date"))}
                         for h in as_list(dig(special, "operationHours", "businessHolidays")) if isinstance(h, dict)] or None,
            "last_updated": text(dig(header, "operationHours", "regularHoursLastUpdated")),
        },
        "attributes": attributes(ld.get("businessAttributesByAliases")) or None,
        "amenities": amenities(props) or None,
        "vibe": {
            "tags": [text(v.get("displayText")) for v in as_list(vibe.get("vibeProperties")) if isinstance(v, dict) and text(v.get("displayText"))] or None,
            "photo_groups": [{"alias": c.get("alias"), "name": text(c.get("label")), "photo_count": to_int(c.get("count")),
                              "photos": [media_photo(p) for p in as_list(c.get("photos"))]}
                             for c in as_list(vibe.get("carousels")) if isinstance(c, dict) and c.get("alias") != "all"] or None,
        } if vibe else None,
        "popular_dishes": popular_dishes(dig(menu_data, "popularX")) or None,
        "menu": {"yelp_link": menu_yelp, "external_link": menu_ext} if (menu_yelp or menu_ext) else None,
        "has_online_ordering": menu_biz.get("onlineOrderingIsSupportedForPlatform"),
        "messaging": {
            "is_enabled": dig(menu_biz, "messaging", "enabledness", "isEnabled"),
            "type": (dig(menu_biz, "messaging", "usecase") or "").lower() or None,
            "response_rate": num(responsive.get("responseRate")),
            "response_time_minutes": to_int(responsive.get("responseTime")),
            "response_time": text(responsive.get("responseTimeText")),
        } if menu_biz.get("messaging") else None,
        "about": {
            "specialties": paragraphs(about.get("specialties")),
            "history": paragraphs(history.get("description")),
            "year_established": year,
            "owner": {"name": text(owner.get("displayName")), "role": text(owner.get("role")),
                      "bio": paragraphs(owner.get("biographyText")),
                      "photo_link": photo_link(dig(owner, "bioPhoto", "photoUrl", "url"), "o")} if owner.get("displayName") else None,
        } if (about.get("specialties") or history.get("description") or year or owner.get("displayName")) else None,
        "services": services(jobs) or None,
        "portfolio": portfolio(txn.get("portfolio")) or None,
        "licenses": licenses(lic if lic is not None else txn.get("verifiedLicenses")) or None,
        "health_inspections": health_inspections(health.get("healthInspections") or props.get("healthInspections")) or None,
        "consumer_alert": {"type": consumer_alert.get("alertType"), "is_harsh": consumer_alert.get("isHarsh")}
        if consumer_alert.get("alertType") else None,
        "past_consumer_alerts": [text(a.get("title") or a.get("alertType") or a) if isinstance(a, dict) else text(a)
                                 for a in as_list(alerts)] or None,
        "primary_photo": photo(encid=primary.get("encid"), url=dig(primary, "photoUrl", "url")) if primary else None,
        "exterior_photo": photo(encid=exterior.get("encid"), url=dig(exterior, "photoUrl", "url")) if exterior else None,
        "is_closed": header.get("isClosed") if header.get("isClosed") is not None else hours.get("isClosed"),
        "closed_until": iso_date(header.get("closedUntil")) if header.get("closedUntil") else None,
        "is_claimed": claim.get("isClaimed"),
        "is_claimable": claim.get("isClaimable"),
        "has_storefront": contact.get("hasStorefrontAddress"),
        "is_online_business": online,
        "is_multi_location": header.get("isMultiloc"),
        "is_yelp_advertiser": photo_header.get("isYelpAdvertiser"),
        "is_yelp_guaranteed": dig(txn, "yelpGuaranteed", "enrolled"),
        "alternate_links": [{"locale": a.get("locale"), "link": a.get("url")} for a in as_list(meta.get("alternateTags"))
                            if isinstance(a, dict) and a.get("url")] or None,
    }


# ---- business cards (search / batch / related) ------------------------------------------------

def business_card(section=None, structured=None, mapdata=None, contact=None):
    """Merge the per-business list ops into one compact card."""
    s, st, m, c = section or {}, structured or {}, mapdata or {}, contact or {}
    alias = s.get("alias") or st.get("alias") or c.get("alias")
    loc = s.get("location") or {}
    price_display = dig(s, "priceRange", "display") or dig(st, "priceRange", "display") or dig(m, "priceRange", "display")
    pp = st.get("primaryPhoto") or m.get("primaryPhoto") or {}
    website = dig(c, "externalResources", "website") or {}
    return {
        "id": s.get("encid") or st.get("encid") or m.get("encid") or c.get("encid"),
        "alias": alias,
        "name": text(s.get("name") or st.get("name") or m.get("name")),
        "link": biz_link(alias),
        "rating": num(s.get("rating") if s.get("rating") is not None else (st.get("rating") if st.get("rating") is not None else m.get("rating"))),
        "review_count": to_int(s.get("reviewCount") if s.get("reviewCount") is not None else (st.get("reviewCount") if st.get("reviewCount") is not None else m.get("reviewCount"))),
        "price_range": price_display,
        "price_level": price_level(price_display),
        "categories": merge_categories(categories(st.get("categories")), categories(m.get("categories")), categories(s.get("categories"))),
        "phone": text(dig(c, "phoneNumber", "formatted")),
        "website": website.get("url"),
        "address": address(loc.get("address"), None, dig(c, "location", "address", "formatted")),
        "neighborhoods": [text(n) for n in as_list(loc.get("neighborhoods")) if text(n)] or None,
        "coordinates": coordinates(dig(m, "location", "geoCoordinate")),
        "service_area": [text(a) for a in as_list(dig(c, "serviceArea", "areas")) if text(a)] or
        ([text(dig(s, "serviceArea", "primaryLocation", "formatted"))] if dig(s, "serviceArea", "primaryLocation", "formatted") else None),
        "timezone": dig(s, "operationHours", "timezone"),
        "photo": photo(encid=pp.get("encid"), url=dig(pp, "photoUrl", "contentUrl") or dig(pp, "photoUrl", "url"),
                       caption=pp.get("caption"), uploaded_at=dig(pp, "metadata", "uploadDate", "utcDateTime")) if pp else None,
        "licenses": licenses(s.get("verifiedLicenses")) or None,
        "has_active_alert": bool(s.get("activeAlert")) if "activeAlert" in s else None,
        "is_yelp_guaranteed": dig(s, "yelpGuaranteed", "enrolled"),
    }


def cards_by_id(results, ids):
    """{op: data} of the list ops for `ids` (+ per-business contact ops keyed
    'contact:<id>') -> {id: card}."""
    def index(op, key="businesses"):
        return {b.get("encid"): b for b in as_list(dig(results, op, key)) if isinstance(b, dict) and b.get("encid")}
    section, structured, mapdata = index("GetResultsSectionData"), index("GetStructuredBusinessListData"), index("GetMapData")
    out = {}
    for biz_id in ids:
        contact = dig(results, f"contact:{biz_id}", "business") or {}
        if not (section.get(biz_id) or structured.get(biz_id) or mapdata.get(biz_id) or contact):
            continue
        out[biz_id] = business_card(section.get(biz_id), structured.get(biz_id), mapdata.get(biz_id), contact)
    return out


# ---- reviews ----------------------------------------------------------------------------------

_REACTIONS = {"HELPFUL": "helpful", "THANKS": "thanks", "LOVE_THIS": "love_this", "OH_NO": "oh_no",
              "USEFUL": "useful", "FUNNY": "funny", "COOL": "cool"}


def reactions(container):
    out = {}
    for r in as_list(dig(container, "availableReactions")):
        if isinstance(r, dict) and r.get("reactionType") in _REACTIONS:
            out[_REACTIONS[r["reactionType"]]] = to_int(r.get("count"))
    return out or None


def review(node, business=None):
    if not isinstance(node, dict) or not node.get("encid"):
        return None
    txt = node.get("text") if isinstance(node.get("text"), dict) else {"full": node.get("text")}
    full = txt.get("full")
    if isinstance(full, str):
        # keyword-search / topic feeds wrap the matches in [[HIGHLIGHT]] markers
        full = full.replace("[[HIGHLIGHT]]", "").replace("[[ENDHIGHLIGHT]]", "")
    tags = node.get("tags") or {}
    reply = node.get("bizUserPublicReply") or {}
    update = node.get("latestReviewUpdate") or {}
    biz = node.get("business") or node.get("businessPassport") or {}
    rod = tags.get("reviewOfTheDay")
    out = {
        "id": node.get("encid"),
        "link": (f"{biz_link(biz.get('alias') or (business or {}).get('alias'))}?hrid={node['encid']}"
                 if (biz.get("alias") or (business or {}).get("alias")) else None),
        "rating": to_int(node.get("rating")),
        "text": paragraphs(full),
        "language": txt.get("language"),
        "translated_text": paragraphs(txt.get("translated")),
        "created_at": utc_datetime(dig(node, "createdAt", "localDateTimeForBusiness") or dig(node, "createdAt", "utcDateTime")),
        "date": local_date(dig(node, "createdAt", "localDateTimeForBusiness")),
        "reactions": reactions(node.get("availableReactionsContainer")),
        "photos": [p for p in (media_photo(x) for x in as_list(node.get("businessPhotos"))) if p] or None,
        "videos": [v for v in (video(x) for x in as_list(node.get("businessVideos"))) if v] or None,
        "author": author(node.get("author")),
        "owner_reply": {
            "text": paragraphs(reply.get("text")),
            "created_at": utc_datetime(dig(reply, "createdAt", "localDateTimeForBusiness") or dig(reply, "createdAt", "utcDateTime")),
            "author": {"name": text(dig(reply, "owner", "displayName")), "role": text(dig(reply, "owner", "role")),
                       "photo_link": photo_link(dig(reply, "owner", "profilePhoto", "photoUrl", "url"), "o")},
        } if reply.get("text") else None,
        "previous_reviews": [p for p in (review(x) for x in as_list(node.get("previousReviews"))) if p] or None,
        "is_updated": bool(update) if update is not None else None,
        "is_first_review": tags.get("isFirstReviewer"),
        "check_in_count": to_int(tags.get("checkInCount")),
        "review_of_the_day": iso_date(rod.get("date") if isinstance(rod, dict) else rod) if rod else None,
        "made_reservation": dig(tags, "reservationInfo", "hasPlacedReservation"),
        "paid_through_yelp": dig(tags, "paymentInfo", "hasPaidThroughYelp"),
        "expert_badge": text(dig(node, "earnedExpertRecognition", "expertRecognition", "displayName")),
        "was_appreciated_by_business": bool(node.get("appreciation")) if "appreciation" in node else None,
    }
    if biz and biz.get("encid") and (business or {}).get("encid") != biz.get("encid"):
        out["business"] = {"id": biz.get("encid"), "alias": biz.get("alias"), "name": text(biz.get("name")),
                           "link": biz_link(biz.get("alias")), "rating": num(biz.get("rating")),
                           "review_count": to_int(biz.get("reviewCount"))}
    return out


def review_feed(business):
    """GetBusinessReviewFeed business -> (reviews, total, stats)."""
    b = business or {}
    conn = b.get("searchReviews") if b.get("searchReviews") is not None else b.get("reviews")
    ctx = {"encid": b.get("encid"), "alias": b.get("alias")}
    items = [r for r in (review(n, ctx) for n in edges(conn)) if r]
    total = to_int(dig(conn, "totalCount"))
    if b.get("searchReviews") is not None:
        # Keyword search reports page_size + 1 as its "total" (a has-more
        # marker), so the caller paginates on has_next instead.
        total = None
    return items, total, bool(dig(conn, "pageInfo", "hasNextPage")), {
        "rating": num(b.get("rating")),
        "review_count": to_int(b.get("reviewCount")),
        "rating_distribution": rating_distribution(b.get("reviewCountsByRating")),
        "languages": language_counts(b.get("reviewCountsByLanguage")),
    }


def review_highlights(business):
    out = []
    for h in as_list(dig(business, "reviewHighlights")):
        if not isinstance(h, dict):
            continue
        snippet = "".join(n.get("text") or "" for n in as_list(h.get("snippetTextNodes")) if isinstance(n, dict))
        phrase = "".join(n.get("text") or "" for n in as_list(h.get("snippetTextNodes")) if isinstance(n, dict) and n.get("isHighlighted"))
        rv = h.get("review") or {}
        ph = h.get("photo") or {}
        out.append({
            "id": h.get("identifier"), "phrase": text(phrase), "snippet": text(snippet),
            "review_count": to_int(h.get("reviewCount")), "type": h.get("highlightType"),
            "review_id": rv.get("encid"), "author": author(rv.get("author")),
            "photo": photo(encid=ph.get("encid"), url=dig(ph, "photoUrl", "url")) if ph else None,
        })
    return out


def review_topics(business):
    out = []
    for t in as_list(dig(business, "reviewInsightTopics")):
        if not isinstance(t, dict):
            continue
        pct = t.get("reviewPercentages") or {}
        out.append({"name": text(t.get("name")), "sentiment": (t.get("sentiment") or "").lower() or None,
                    "review_count": to_int(t.get("numberOfReviews")),
                    "positive_share": _share(pct.get("positive")), "neutral_share": _share(pct.get("neutral")),
                    "critical_share": _share(pct.get("critical"))})
    return out


def _share(percent):
    n = num(percent)
    return round(n / 100.0, 4) if n is not None else None


def topic_reviews(business):
    conn = dig(business, "searchReviewInsights") or {}
    out = []
    for node in edges(conn):
        r = review(node.get("review") or {}, {"alias": None})
        if r is None:
            continue
        r["matched_snippet"] = highlight_text(node.get("snippet"))
        out.append(r)
    return out, to_int(conn.get("totalCount"))


# ---- not-recommended reviews (server-rendered HTML) ----------------------------------------------

_NR_ITEM_RE = re.compile(r'<li class="[^"]*">(.*?)</li>(?=<li class=|</ul>)', re.S)


def not_recommended_reviews(page_html):
    """/not_recommended_reviews/<alias> -> (reviews, total, removed_total).
    The page lists 10 not-recommended reviews, then a fixed sample of reviews
    "removed for violating our Terms of Service" (author + date only — only
    their count is kept). Class names are hashed and change; the anchors
    used are aria-labels and ids."""
    html = page_html or ""
    plain = re.sub(r"<[^>]+>", "", html[:600000])
    m = re.search(r"([\d,]+)\s+reviews?\s+for\s+.{1,200}?\s+that\s+(?:is|are)\s+not\s+currently\s+recommended", plain)
    total = to_int(m.group(1)) if m else None
    m = re.search(r"([\d,]+)\s+reviews?\s+removed\s+for\s+violating", plain)
    removed = to_int(m.group(1)) if m else None
    out = []
    for block in re.split(r'(?=<div class="[^"]*" role="region" aria-label="[^"]+"><div class="arrange)', html)[1:]:
        name = re.match(r'<div class="[^"]*" role="region" aria-label="([^"]+)"', block)
        if not name:
            continue
        notice = block.find("removed for violating")
        if notice >= 0:
            first_text = block.find("expander-link-content")
            if first_text < 0 or first_text > notice:
                continue                     # a removed review (author + date, no text)
            block = block[:notice]           # the last real review runs into the removed-section heading
        stats = {k.lower(): to_int(v) for k, v in re.findall(
            r'aria-label="(Friends|Reviews|Photos)".*?<span[^>]*>([\d,]+)</span>', block, re.S)}
        rating = re.search(r'aria-label="(\d(?:\.\d)?) star rating"', block)
        date = re.search(r'star rating".*?<p class="[^"]*">([A-Z][a-z]{2} \d{1,2}, \d{4})</p>', block, re.S)
        body_text = re.search(r'id="expander-link-content-[^"]*"><p class="[^"]*">(.*?)</p>', block, re.S)
        avatar = re.search(r'<img[^>]+src="([^"]+)"[^>]+alt="Photo of', block)
        if not (rating or body_text):
            continue
        avatar_url = avatar.group(1) if avatar else None
        out.append({
            "rating": to_int(rating.group(1)) if rating else None,
            "text": paragraphs(body_text.group(1)) if body_text else None,
            "date": us_date(date.group(1)) if date else None,
            "author": {
                "name": text(html_lib.unescape(name.group(1))),
                "photo_link": photo_link(avatar_url, "o") if avatar_url and "default_user_avatar" not in avatar_url else None,
                "review_count": stats.get("reviews"), "friend_count": stats.get("friends"), "photo_count": stats.get("photos"),
            },
        })
    return out, total, removed


# ---- photos -----------------------------------------------------------------------------------------

def photo_grid(business):
    """GetBizPhotosMediaGrid businessByEncidOrAlias -> (photos, total, tabs)."""
    b = business or {}
    media = b.get("media") or {}
    conn = media.get("photoCaptionSearchResults") or b.get("activePhotosConnection") or media.get("orderedMediaItems") or {}
    photos = []
    for node in edges(conn):
        if node.get("videoUrl") or node.get("videoPublication"):
            photos.append(dict(video(node) or {}, type="video"))
            continue
        p = media_photo(node)
        if p:
            review_node = node.get("mediaReview") or {}
            p["review_id"] = review_node.get("encid")
            photos.append(p)
    tabs = [{"alias": t.get("alias"), "name": text(t.get("label")), "photo_count": to_int(t.get("count"))}
            for t in as_list(media.get("photoTabs")) if isinstance(t, dict)]
    return photos, to_int(conn.get("totalCount")), tabs


def dish_mentions(raw):
    """{dish id: {"photo_count", "photos"}} — a dish can be listed twice
    (the second time with no photos), so entries are merged."""
    out = {}
    for group in as_list(dig(raw, "popularX", "lightbox", "popularXMentions")):
        for mention in as_list(dig(group, "mentions")):
            if not isinstance(mention, dict) or not mention.get("identifier"):
                continue
            cur = out.setdefault(mention["identifier"], {"photo_count": None, "photos": []})
            cur["photo_count"] = cur["photo_count"] or to_int(mention.get("totalCount"))
            seen = {p["id"] for p in cur["photos"]}
            for p in as_list(mention.get("photos")):
                photo_obj = media_photo(p) if isinstance(p, dict) else None
                if photo_obj and photo_obj["id"] not in seen:
                    cur["photos"].append(photo_obj)
                    seen.add(photo_obj["id"])
    return out


def lightbox_media(business):
    """GetLightboxData business -> (items, total, tabs); used for videos."""
    media = dig(business, "media") or {}
    conn = media.get("orderedMediaItems") or {}
    items = []
    for node in edges(conn):
        if node.get("videoUrl") or node.get("__typename") == "BusinessVideo":
            v = video(node)
            if v:
                items.append(dict(v, type="video"))
        else:
            p = media_photo(node)
            if p:
                items.append(dict(p, type="photo"))
    tabs = [{"alias": t.get("alias"), "name": text(t.get("label")), "photo_count": to_int(t.get("count"))}
            for t in as_list(media.get("photoTabs")) if isinstance(t, dict)]
    return items, to_int(conn.get("totalCount")), tabs


# ---- menu (server-rendered /menu/<alias>) -------------------------------------------------------------

def menu(page_html):
    html = page_html or ""
    m = re.search(r'<script type="application/ld\+json">\s*(\{.*?"@type"\s*:\s*"Menu".*?\})\s*</script>', html, re.S)
    ld = {}
    if m:
        try:
            ld = json.loads(m.group(1))
        except ValueError:
            ld = {}
    extras = {}
    for block in re.split(r'<div class="menu-item">', html)[1:]:
        link = re.search(r'<h4>\s*<a href="([^"]+)"', block)
        if not link:
            continue
        img = re.search(r'<img[^>]+class="photo-box-img"[^>]+src="([^"]+)"', block) or \
            re.search(r'<img[^>]+src="([^"]+)"[^>]+class="photo-box-img"', block)
        reviews = re.search(r'([\d,]+)\s+reviews?</a>', block)
        photos = re.search(r'([\d,]+)\s+photos?</a>', block)
        extras[link.group(1).split("#")[0]] = {
            "photo_link": photo_link(img.group(1), "o") if img else None,
            "review_count": to_int(reviews.group(1)) if reviews else None,
            "photo_count": to_int(photos.group(1)) if photos else None,
        }
    sections = []
    for sec in as_list(ld.get("hasMenuSection")):
        if not isinstance(sec, dict):
            continue
        items = []
        for item in as_list(sec.get("hasMenuItem")):
            if not isinstance(item, dict):
                continue
            offers = item.get("offers") or {}
            offers = offers[0] if isinstance(offers, list) and offers else offers
            price, currency = money(offers.get("price") if isinstance(offers, dict) else None,
                                    offers.get("priceCurrency") if isinstance(offers, dict) else None)
            path = item.get("url")
            extra = extras.get(path) or {}
            items.append({"name": text(item.get("name")), "description": text(item.get("description")),
                          "price": price, "currency": currency if price is not None else None,
                          "link": absolute(path), "photo_link": extra.get("photo_link"),
                          "review_count": extra.get("review_count"), "photo_count": extra.get("photo_count")})
        sections.append({"name": text(sec.get("name")), "description": text(sec.get("description")), "items": items})
    title = text(ld.get("name"))
    return {"name": title, "sections": sections}


# ---- Q&A / posts ----------------------------------------------------------------------------------------

def generated_answer(raw):
    if not isinstance(raw, dict) or not raw.get("text") or raw.get("isBaaRejected"):
        return None
    return {"text": paragraphs(raw.get("text")), "short_answer": text(dig(raw, "metadata", "shortAnswer"))}


def answer(node):
    if not isinstance(node, dict) or not node.get("encid"):
        return None
    return {"id": node.get("encid"), "text": paragraphs(node.get("text")),
            "helpful_count": to_int(node.get("helpfulVoteCount")),
            "created_at": utc_datetime(dig(node, "createdAt", "utcDateTime")),
            "author": author(node.get("author")) or ({"name": text(dig(node, "author", "displayName"))} if dig(node, "author", "displayName") else None)}


def question(node, business_alias=None):
    if not isinstance(node, dict) or not node.get("encid"):
        return None
    biz = node.get("business") or {}
    biz_id = biz.get("encid")
    return {
        "id": node.get("encid"),
        "link": f"{SITE}/questions/{biz_id}/{node['encid']}" if biz_id else None,
        "text": paragraphs(node.get("text")),
        "answer_count": to_int(dig(node, "answers", "totalCount")),
        "top_answer": answer(node.get("topAnswer")),
        "ai_answer": generated_answer(node.get("generatedBAAAnswer")),
        "created_at": utc_datetime(dig(node, "createdAt", "utcDateTime")),
        "author": author(node.get("author")) or ({"id": dig(node, "author", "encid"), "name": text(dig(node, "author", "displayName")),
                                                  "link": user_link(dig(node, "author", "encid"))} if dig(node, "author", "encid") else None),
    }


def questions(business):
    conn = dig(business, "communityQuestions") or {}
    items = [q for q in (question(n) for n in edges(conn)) if q]
    return items, to_int(conn.get("totalCount"))


def question_details(raw):
    q = raw.get("businessCommunityQuestion") if isinstance(raw, dict) else None
    q = q or {}
    base = question(q) or {}
    conn = q.get("answers") or {}
    answers = [a for a in (answer(n) for n in edges(conn)) if a]
    biz = q.get("business") or {}
    base.pop("top_answer", None)
    base["business"] = {"id": biz.get("encid"), "alias": biz.get("alias"), "name": text(biz.get("name")),
                        "link": biz_link(biz.get("alias"))} if biz.get("encid") else None
    return base, answers, to_int(conn.get("totalCount"))


def _prefixed(photo_url, suffix=".jpg", size="o"):
    """{urlPrefix, urlSuffix} photo URLs -> a full link at `size`."""
    prefix = dig(photo_url, "urlPrefix")
    if not prefix:
        return None
    return f"{prefix}{size if prefix.endswith('/') else ''}{dig(photo_url, 'urlSuffix') or suffix}"


def posts(business):
    """GetBusinessPosts business -> business updates / announcements."""
    out = []
    for node in edges(dig(business, "nonDeletedPosts")):
        media = []
        for m in as_list(node.get("media")):
            if isinstance(m, dict) and m.get("urlPrefix"):
                is_video = m.get("__typename") == "BusinessPostVideo"
                media.append({"id": m.get("encId"), "type": "video" if is_video else "photo",
                              "link": m["urlPrefix"] + ("" if is_video else "o.jpg") if m["urlPrefix"].endswith("/") else m["urlPrefix"]})
        video_links = [r.get("src") for r in as_list(dig(node, "videoPublication", "renditionSet")) if isinstance(r, dict) and r.get("src")]
        reactions = {(r.get("type") or "").lower(): to_int(r.get("count")) for r in as_list(node.get("reactionRundowns"))
                     if isinstance(r, dict) and r.get("type")}
        image = node.get("image") or {}
        out.append({
            "id": node.get("encId") or node.get("encid"),
            "headline": text(node.get("headline")),
            "text": paragraphs(node.get("description")),
            "created_at": utc_datetime(dig(node, "created", "utcDateTime")),
            "event_starts_at": utc_datetime(dig(node, "eventStartDate", "utcDateTime")),
            "link": absolute(node.get("linkUrl")),
            "call_to_action": text(node.get("ctaLabel")) or (text(node.get("ctaAction")) or "").lower() or None,
            "photo_link": _prefixed(image.get("photoUrl")) if image else None,
            "media": media or None,
            "video_links": video_links or None,
            "reactions": reactions or None,
        })
    return out


# ---- search (/search/snippet) ------------------------------------------------------------------------------

def _snippet_result(r):
    srb = r.get("searchResultBusiness") or {}
    snippet = r.get("snippet") or {}
    highlights = [text(strip_tags(h.get("title"))) for h in as_list(dig(r, "searchResultBusinessHighlights", "businessHighlights"))
                  if isinstance(h, dict)]
    actions = []
    for a in as_list(r.get("searchActions")):
        label = strip_tags(dig(a, "content", "text", "text")) or text(dig(a, "buttonProps", "text"))
        link = dig(a, "buttonProps", "attributes", "linkoutUrl")
        if label:
            actions.append({"label": label, "link": link})
    photos = [photo(url=p.get("src")) for p in as_list(dig(r, "scrollablePhotos", "photoList")) if isinstance(p, dict) and p.get("src")]
    projects = [{"id": p.get("projectId"), "caption": text(p.get("caption")), "photo_link": photo_link(p.get("photoSrc"), "o")}
                for p in as_list(r.get("searchResultBusinessPortfolioProjects")) if isinstance(p, dict)]
    return {
        "rank": to_int(r.get("ranking")),
        "snippet": highlight_text(snippet.get("text")),
        "snippet_type": snippet.get("type"),
        "highlights": [h for h in highlights if h] or None,
        "tags": [strip_tags(dig(t, "label", "text")) for t in as_list(r.get("tags")) if strip_tags(dig(t, "label", "text"))] or None,
        "actions": actions or None,
        "photos": [p for p in photos if p] or None,
        "portfolio_projects": projects or None,
        "licenses": licenses(dig(r, "verifiedLicenseInfo", "licenses")) or None,
        "_srb": srb,
    }


def search_results(snippet_json):
    """/search/snippet JSON -> (organic [{bizId + extras}], sponsored, context)."""
    props = dig(snippet_json, "searchPageProps") or {}
    organic, sponsored = [], []
    for comp in as_list(props.get("mainContentComponentsListProps")):
        if not isinstance(comp, dict) or comp.get("type") != "searchResultSection":
            continue
        for r in as_list(dig(comp, "props", "searchResults")):
            if not isinstance(r, dict) or not r.get("bizId"):
                continue
            item = _snippet_result(r)
            item["id"] = r["bizId"]
            (sponsored if r.get("isAd") else organic).append(item)
    ctx = props.get("searchContext") or {}
    header = next((c.get("props") for c in as_list(props.get("mainContentComponentsListProps"))
                   if isinstance(c, dict) and c.get("type") == "searchHeader"), None) or {}
    did_you_mean = dig(header, "didYouMeanData")
    return organic, sponsored, {
        "total": to_int(ctx.get("totalResults")),
        "per_page": to_int(ctx.get("resultsPerPage")) or 10,
        "start": to_int(ctx.get("startResult")) or 0,
        "title": text(dig(header, "descriptionData", "rawDescription")),
        "did_you_mean": text(dig(did_you_mean, "suggestedText") or dig(did_you_mean, "text")) if isinstance(did_you_mean, dict) else None,
    }


def sponsored_card(item):
    srb = item.get("_srb") or {}
    alias = srb.get("alias")
    return {
        "id": item.get("id"), "alias": alias, "name": text(srb.get("name")), "link": biz_link(alias),
        "rating": num(srb.get("rating")), "review_count": to_int(srb.get("reviewCount")),
        "price_range": srb.get("priceRange") or None, "price_level": price_level(srb.get("priceRange")),
        "categories": [{"alias": None, "title": text(c.get("title"))} for c in as_list(srb.get("categories")) if isinstance(c, dict)],
        "phone": text(srb.get("phone")),
        "neighborhoods": [text(n) for n in as_list(srb.get("neighborhoods")) if text(n)] or None,
        "snippet": item.get("snippet"), "highlights": item.get("highlights"),
        "photo": (item.get("photos") or [None])[0],
    }


def filters(snippet_json):
    """filterPanelProps -> [{group, title, type, options: [{value, label, is_selected}]}]."""
    panel = dig(snippet_json, "searchPageProps", "filterPanelProps") or {}
    info = panel.get("filterInfoMap") or {}
    groups = []
    order = as_list(panel.get("filterPanelOrdering")) + [k for k in (panel.get("filterSetMap") or {}) if k not in as_list(panel.get("filterPanelOrdering"))]
    for key in order:
        fs = dig(panel, "filterSetMap", key)
        if not isinstance(fs, dict):
            continue
        values = []
        for v in as_list(fs.get("filters")):
            if v not in values:
                values.append(v)
        for more in as_list(fs.get("moreFilters")):
            for v in as_list(dig(more, "subfilters")):
                if v not in values:
                    values.append(v)
        options = []
        for v in values:
            f = info.get(v) or next((x for x in info.values() if isinstance(x, dict) and x.get("value") == v), None) or {}
            options.append({"value": f.get("value") or v, "label": text(f.get("text")),
                            "is_selected": bool(f.get("isSelected"))})
        groups.append({"group": key, "title": text(fs.get("title")), "type": fs.get("type"), "options": options})
    return groups


# ---- autocomplete ------------------------------------------------------------------------------------------

def suggestions(raw, key):
    out = []
    for s in as_list(dig(raw, "searchSuggestFrontend", key, "suggestions")):
        if not isinstance(s, dict):
            continue
        redirect = absolute(s.get("redirectUrl"))
        alias = None
        if redirect and "/biz/" in redirect:
            alias = redirect.split("/biz/", 1)[1].split("?")[0].split("/")[0]
        out.append({"text": text(s.get("query") or s.get("title")), "title": text(s.get("title")),
                    "subtitle": text(s.get("subtitle")), "type": s.get("type"),
                    "business_alias": alias, "link": redirect})
    return out


# ---- users ------------------------------------------------------------------------------------------------------

_COMPLIMENT_KEYS = {"thankYou": "thank_you", "goodWriter": "good_writer", "greatPhoto": "great_photo", "justANote": "just_a_note",
                    "cutePic": "cute_pic", "hotStuff": "hot_stuff", "likeYourProfile": "like_your_profile",
                    "writeMore": "write_more", "youAreCool": "you_are_cool", "greatLists": "great_lists",
                    "youAreFunny": "you_are_funny"}


def user_profile(profile, about=None, impact=None, elite=None):
    u = dig(profile, "user") or {}
    ab = dig(about, "user") or {}
    im = dig(impact, "user") or {}
    el = dig(elite, "user") or {}
    photos = [p for p in (photo(encid=n.get("encid"), url=dig(n, "photoUrl", "url")) for n in edges(u.get("profilePhotos"))) if p]
    counts = dig(im, "compliments", "approvedCounts") or {}
    received = dig(im, "contentReactions", "receivedCount")
    year = elite_year(u.get("currentTruncatedEliteYear"))
    return {
        "id": u.get("encid"),
        "name": text(u.get("displayName")),
        "first_name": text(u.get("firstName")),
        "link": user_link(u.get("encid")),
        "location": text(u.get("displayLocation") or ab.get("displayLocation")),
        "tagline": text(dig(u, "about", "tagline")),
        "joined": text(ab.get("joinedYelpMonth")),
        "about": [{"question": text(q.get("prompt")), "answer": paragraphs(q.get("answer"))}
                  for q in as_list(dig(ab, "about", "bioQuestions")) if isinstance(q, dict) and q.get("answer")] or None,
        "review_count": to_int(u.get("reviewCount")),
        "review_update_count": to_int(im.get("reviewUpdateCount")),
        "first_to_review_count": to_int(im.get("firstToReviewCount")),
        "photo_count": to_int(u.get("businessPhotoCount")),
        "video_count": to_int(u.get("businessVideoCount")),
        "friend_count": to_int(u.get("friendCount")),
        "follower_count": to_int(dig(u, "followers", "totalCount") if dig(u, "followers", "totalCount") is not None else dig(im, "followers", "totalCount")),
        "following_count": to_int(dig(u, "following", "totalCount")),
        "question_count": to_int(dig(u, "businessCommunityQuestions", "totalCount")),
        "answer_count": to_int(dig(u, "businessCommunityAnswers", "totalCount")),
        "events_created_count": to_int(u.get("eventsCreatedCount")),
        "expert_recognition_count": to_int(dig(u, "expertRecognitions", "earned", "totalCount")),
        "compliment_count": to_int(dig(u, "compliments", "approvedCount")),
        "compliments": {_COMPLIMENT_KEYS.get(k, k): to_int(v) for k, v in counts.items() if k in _COMPLIMENT_KEYS} or None,
        "reactions_received": to_int(received[0] if isinstance(received, list) and received else received),
        "elite_year": year,
        "elite_years": sorted({to_int(y) for y in as_list(el.get("eliteYears") or u.get("eliteYears")) if to_int(y)}) or None,
        "is_elite": year is not None,
        "is_elite_all_star": bool(u.get("isEliteAllStar")) if u.get("isEliteAllStar") is not None else None,
        "profile_photos": photos or None,
    }


def user_reviews(raw):
    u = dig(raw, "user") or {}
    conn = u.get("filteredReviews") or u.get("searchReviews") or {}
    items = []
    for node in edges(conn):
        matched = None
        if isinstance(node.get("review"), dict):          # keyword search wraps each hit
            matched = highlight_text(node.get("highlightedReviewText"))
            node = node["review"]
        r = review(node)
        if r is None:
            continue
        if matched:
            r["matched_snippet"] = matched
        biz = node.get("businessPassport") or node.get("business") or {}
        loc = biz.get("location") or {}
        r["business"] = {
            "id": biz.get("encid"), "alias": biz.get("alias"), "name": text(biz.get("name")), "link": biz_link(biz.get("alias")),
            "rating": num(biz.get("rating")), "review_count": to_int(biz.get("reviewCount")),
            "price_range": dig(biz, "priceRange", "display"),
            "categories": [text(c.get("title")) for c in as_list(biz.get("categories")) if isinstance(c, dict)] or None,
            "address": address(loc.get("address")), "neighborhoods": [text(n) for n in as_list(loc.get("neighborhoods")) if text(n)] or None,
        } if biz.get("encid") else None
        items.append(r)
    return items, to_int(conn.get("totalCount"))


def user_photos(raw):
    conn = dig(raw, "user", "orderedMediaItems") or {}
    out = []
    for node in edges(conn):
        p = media_photo(node)
        if not p:
            continue
        biz = node.get("photoBusiness") or {}
        p.pop("uploaded_by", None)
        p["business"] = {"id": biz.get("encid"), "alias": biz.get("alias"), "name": text(biz.get("name")),
                         "link": biz_link(biz.get("alias"))} if biz.get("encid") else None
        out.append(p)
    return out, to_int(conn.get("totalCount"))


def user_friends(raw):
    conn = dig(raw, "user", "friends", "confirmations") or {}
    return [a for a in (author(n.get("friend")) for n in edges(conn)) if a], to_int(conn.get("totalCount"))


def user_following(raw):
    conn = dig(raw, "user", "following") or {}
    return [a for a in (author(n) for n in edges(conn)) if a], to_int(conn.get("totalCount"))


def compliments(raw):
    conn = dig(raw, "user", "compliments", "approved") or {}
    out = []
    for node in edges(conn):
        out.append({"id": node.get("encid"), "type": (node.get("type") or "").lower() or None,
                    "message": paragraphs(node.get("message")),
                    "created_at": utc_datetime(dig(node, "createdAt", "utcDateTime")),
                    "sender": author(node.get("sender"))})
    return out, to_int(conn.get("totalCount"))


# ---- quick search (genericBusinessSearch) ------------------------------------------------------------------

def quick_search_ids(raw):
    ids = []
    for node in edges(dig(raw, "genericBusinessSearch")):
        biz_id = dig(node, "business", "encid")
        if biz_id and biz_id not in ids:
            ids.append(biz_id)
    return ids


# ---- related businesses (/biz/<id>/props) ---------------------------------------------------------------

def related(props_json):
    p = dig(props_json, "bizDetailsPageProps") or {}
    out = []
    for r in as_list(dig(p, "relatedBusinessesCarouselProps", "relatedBusinesses")):
        if not isinstance(r, dict):
            continue
        link = absolute(r.get("businessUrl"))
        alias = link.split("/biz/", 1)[1].split("?")[0] if link and "/biz/" in link else None
        level = to_int(r.get("priceRange"))
        symbol = r.get("currencySymbol") or "$"
        out.append({
            "alias": alias, "name": text(r.get("name")), "link": biz_link(alias),
            "rating": num(r.get("rating")), "review_count": to_int(r.get("reviewCount")),
            "price_range": symbol * level if level else None, "price_level": level or None,
            "categories": [text(c.get("title")) for c in as_list(r.get("categories")) if isinstance(c, dict) and text(c.get("title"))] or None,
            "photo_link": photo_link(r.get("photoSrc"), "o"),
        })
    collections = []
    for c in as_list(dig(p, "collectionCardCarouselProps", "collections")):
        if not isinstance(c, dict):
            continue
        collections.append({"name": text(c.get("name")), "link": absolute(c.get("url")), "item_count": to_int(c.get("itemCount")),
                            "owner_name": text(dig(c, "owner", "displayName")),
                            "photo_link": photo_link(dig(c, "photos", 0, "sourceUrl"), "o")})
    return out, collections


# ---- events (server-rendered /events pages) ------------------------------------------------------------------

def _meta(block, prop):
    m = re.search(r'<meta itemprop="%s" content="([^"]*)"' % prop, block)
    return html_lib.unescape(m.group(1)) if m else None


def events_list(page_html):
    html = page_html or ""
    out = []
    for block in re.split(r'<div class="card card--sticky-footer', html)[1:]:
        link = re.search(r'<a href="(/events/[^"?#]+)"[^>]*itemprop="url"', block) or re.search(r'href="(/events/[a-z0-9][^"?#/]*-[^"?#/]+)"', block)
        name = re.search(r'<span itemprop="name">([^<]+)</span>', block)
        if not (link and name):
            continue
        img = re.search(r'<img[^>]+src="([^"]+)"', block)
        texts = [text(re.sub(r"<[^>]+>", " ", t)) for t in re.findall(r'<div class="u-text-truncate u-space-b1">(.*?)</div>', block, re.S)]
        texts = [t for t in texts if t]
        when = texts[0] if texts else None
        where = texts[1] if len(texts) > 1 else None
        venue, city = (where.split(" — ", 1) + [None])[:2] if where and " — " in where else (where, None)
        desc = re.search(r'itemprop="description">(.*?)</p>', block, re.S)
        interested = re.search(r'([\d,]+)\s+(?:are|is)\s+interested', block)
        slug = link.group(1).split("/events/", 1)[1]
        out.append({
            "id": slug, "name": text(name.group(1)), "link": SITE + link.group(1),
            "starts_at": utc_datetime(_meta(block, "startDate")), "time_text": when,
            "venue": text(venue), "city": text(city),
            "description": text(re.sub(r"<[^>]+>", " ", desc.group(1))) if desc else None,
            "interested_count": to_int(interested.group(1)) if interested else None,
            "photo_link": photo_link(img.group(1), "o") if img else None,
        })
    return out


def _itemprop(html, prop):
    m = re.search(r'<meta[^>]+itemprop="%s"[^>]+content="([^"]*)"' % prop, html) or \
        re.search(r'<meta[^>]+content="([^"]*)"[^>]+itemprop="%s"' % prop, html)
    if m:
        return html_lib.unescape(m.group(1))
    m = re.search(r'<(\w+)[^>]*itemprop="%s"[^>]*>(.*?)</\1>' % prop, html, re.S)
    return m.group(2) if m else None


def event_details(page_html, slug):
    """/events/<slug> (legacy server-rendered page, schema.org Event microdata)."""
    html = page_html or ""
    start = html.find('itemtype="http://schema.org/Event"')
    scope = html[start:] if start >= 0 else html
    place_at = scope.find('itemtype="http://schema.org/Place"')
    place = scope[place_at:place_at + 3000] if place_at >= 0 else ""
    h1 = re.search(r'<h1[^>]*itemprop="name"[^>]*>(.*?)</h1>', scope, re.S)
    name = strip_tags(h1.group(1)) if h1 else strip_tags(_itemprop(scope, "name"))
    cats = [text(c) for c in re.findall(r'<span class="category-str-list">(.*?)</span>', scope, re.S)[:1]]
    category_names = [text(re.sub(r"<[^>]+>", "", c)) for c in re.findall(r'<a href="/events/[^"]+/browse\?c=\d+">([^<]+)</a>', cats[0] if cats else "")]
    ticket = re.search(r'<span class="event-details_ticket-info">.*?</span>\s*([^<]+)</span>', scope, re.S)
    price_text = text(ticket.group(1)) if ticket else None
    price, currency = money(price_text) if price_text and re.search(r"\d", price_text) else (None, None)
    website = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(?:(?!</a>).){0,1500}?Official Website', scope, re.S)
    website_link = None
    if website:
        raw = html_lib.unescape(website.group(1))
        m = re.search(r"[?&]url=([^&]+)", raw)
        from urllib.parse import unquote
        website_link = unquote(m.group(1)) if m else absolute(raw)
    desc = re.search(r'<p itemprop="description">(.*?)</p>', scope, re.S)
    description = paragraphs(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", desc.group(1)))) if desc else None
    interested = re.search(r"([\d,]+)\s+(?:are|is)\s+interested", scope)
    event_id = re.search(r"/events/interested/([A-Za-z0-9_-]{22})", scope) or re.search(r"flag_id=([A-Za-z0-9_-]{22})&amp;flag_type=event", scope)
    biz_path = _itemprop(place, "url")
    biz_alias = biz_path.split("/biz/", 1)[1] if biz_path and "/biz/" in biz_path else None
    image = _itemprop(scope, "image")
    return {
        "id": slug,
        "event_id": event_id.group(1) if event_id else None,
        "name": name,
        "link": f"{SITE}/events/{slug}",
        "description": description,
        "starts_at": utc_datetime(_itemprop(scope, "startDate")),
        "ends_at": utc_datetime(_itemprop(scope, "endDate")),
        "categories": category_names or None,
        "is_official_yelp_event": "browse?official=1" in (cats[0] if cats else ""),
        "is_free": (price_text or "").lower() == "free" if price_text else None,
        "price": price, "currency": currency if price is not None else None,
        "price_text": price_text,
        "website": website_link,
        "venue": {
            "name": text(_itemprop(place, "name")),
            "business_alias": biz_alias,
            "business_link": biz_link(biz_alias) if biz_alias else None,
            "address": {"line1": strip_tags(_itemprop(place, "streetAddress")), "city": strip_tags(_itemprop(place, "addressLocality")),
                        "state": strip_tags(_itemprop(place, "addressRegion")), "postal_code": strip_tags(_itemprop(place, "postalCode")),
                        "country_code": text(_itemprop(place, "addressCountry"))},
            "phone": strip_tags(_itemprop(place, "telephone")),
        } if place else None,
        "interested_count": to_int(interested.group(1)) if interested else None,
        "photo_link": photo_link(image, "o") if image else None,
    }
