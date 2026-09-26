"""/yelp/users/* endpoints — all /gql/batch, logged-out (profile, reviews,
photos, friends, following, compliments)."""
from yelp import fetch, parsers
from yelp.shared import dig, page_after, pagination

REVIEW_SORTS = {"newest": "TIME_DESC", "oldest": "TIME_ASC", "highest_rated": "RATING_DESC", "lowest_rated": "RATING_ASC"}
FRIEND_SORTS = {"newest": "TIME_CONFIRMED_DESC", "oldest": "TIME_CONFIRMED_ASC", "name": "FIRST_NAME_ASC",
                "name_desc": "FIRST_NAME_DESC", "recently_reviewed": "TIME_LAST_REVIEWED_DESC"}
REACTION_TYPES = ["HELPFUL", "THANKS", "LOVE_THIS", "OH_NO"]


def _require_user(result, user):
    if not dig(result, "data", "user"):
        fetch.raise_for_input(result, f"user {user!r}")
        raise fetch.YelpNotFound(f"user {user!r} not found on Yelp")


def details(user):
    ops = [("GetUserProfilePageData", {"userEncid": user}),
           ("GetProfileOverviewAboutData", {"userEncid": user}),
           ("GetProfileOverviewImpactData", {"userEncid": user, "reviewReactionTypes": REACTION_TYPES}),
           ("GetProfileYearsEliteContentData", {"userEncid": user})]
    profile, about, impact, elite = fetch.gql(ops)
    _require_user(profile, user)
    return parsers.user_profile(dig(profile, "data"), dig(about, "data"), dig(impact, "data"), dig(elite, "data"))


def _user_ref(user):
    return {"id": user, "link": f"https://www.yelp.com/user_details?userid={user}"}


def reviews(user, sort_by, category, query, page, page_size):
    variables = {"userEncid": user, "reactionsSourceFlow": "userProfileReviews", "resultsPerPage": page_size,
                 "after": page_after(page, page_size), "searchText": query or "", "recognitionEncid": "",
                 "isStandard": not query, "isSearching": bool(query), "isRecognition": False}
    if sort_by:
        variables["sort"] = REVIEW_SORTS[sort_by]
    if category:
        variables["categoryAlias"] = category
    result = fetch.gql_one("GetProfileReviewsContentData", variables)
    _require_user(result, user)
    items, total = parsers.user_reviews(dig(result, "data"))
    return {"user": dict(_user_ref(user), name=dig(result, "data", "user", "displayName")), "reviews": items,
            "pagination": pagination(page, page_size, total if total is not None else dig(result, "data", "user", "reviewCount"))}


def photos(user, page, page_size):
    result = fetch.gql_one("GetProfilePhotosMediaGrid", {"userEncid": user, "resultsPerPage": page_size,
                                                         "after": page_after(page, page_size),
                                                         "reactionsSourceFlow": "userProfilePhotos"})
    _require_user(result, user)
    items, total = parsers.user_photos(dig(result, "data"))
    return {"user": dict(_user_ref(user), name=dig(result, "data", "user", "displayName")), "photos": items,
            "pagination": pagination(page, page_size, total)}


def friends(user, sort_by, page, page_size):
    result = fetch.gql_one("GetUserFriendsData", {"userEncid": user, "first": page_size, "after": page_after(page, page_size),
                                                  "sort": FRIEND_SORTS[sort_by or "newest"]})
    _require_user(result, user)
    items, total = parsers.user_friends(dig(result, "data"))
    return {"user": dict(_user_ref(user), name=dig(result, "data", "user", "displayName")), "friends": items,
            "pagination": pagination(page, page_size, total)}


def following(user, page, page_size):
    result = fetch.gql_one("GetUserFollowingData", {"userEncid": user, "first": page_size, "after": page_after(page, page_size)})
    _require_user(result, user)
    items, total = parsers.user_following(dig(result, "data"))
    return {"user": _user_ref(user), "following": items, "pagination": pagination(page, page_size, total)}


def compliments(user, page, page_size):
    result = fetch.gql_one("GetProfileComplimentsContentData", {"userEncid": user, "isCurrentUser": False,
                                                                "resultsPerPage": page_size, "after": page_after(page, page_size)})
    _require_user(result, user)
    items, total = parsers.compliments(dig(result, "data"))
    return {"user": dict(_user_ref(user), name=dig(result, "data", "user", "displayName")), "compliments": items,
            "pagination": pagination(page, page_size, total)}
