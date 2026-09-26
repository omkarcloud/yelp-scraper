"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json.
"""
import json
import os

from yelp.businesses import details, reviews
from yelp.users import details as user_details

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a business alias, its id, or any yelp.com business link
    save("business_gary_danko.json", details("gary-danko-san-francisco"))

    # 6 sorts, star / keyword / language filters, translation — 20 per page
    save("reviews_gary_danko.json", reviews("gary-danko-san-francisco", sort_by="newest", rating=None,
                                            query=None, language=None, translate_to=None, page=1, page_size=20))

    # a reviewer's profile: Elite years, counts, compliments
    save("user_profile.json", user_details("CHV3OXUzMbMDZ5A07UGO5A"))
