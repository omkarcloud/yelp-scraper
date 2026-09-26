# ⭐ Yelp Scraper

Yelp Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Yelp data for free.

## ✨ What Can I Get?

- 🏪 **Full details on 8M+ businesses** — hours, phone, website, amenities, health scores & popular dishes
- 💬 **330M+ reviews** — 6 sorts, star, keyword & language filters, translation, even the hidden "not recommended" ones
- 🔍 **Search like Yelp does** — any keyword or category, any city, price & feature filters
- 📸 **Photos, menus, Q&A & reviewers** — original-size photos, menu prices, Elite reviewer profiles & events

## 🍽️ Example: A Full Yelp Business

```json
{
  "id": "WavvLdfdP6g8aZTtbBQHTw",
  "alias": "gary-danko-san-francisco",
  "name": "Gary Danko",
  "link": "https://www.yelp.com/biz/gary-danko-san-francisco",
  "summary": "Fine dining with customizable menus and a romantic ambiance.",
  "rating": 4.5,
  "review_count": 6150,
  "rating_distribution": { "1": 125, "2": 216, "3": 485, "4": 1100, "5": 4229 },
  "photo_count": 14831,
  "price_range": "$$$$",
  "categories": [
    { "alias": "newamerican", "title": "New American", "root_alias": "restaurants", "path": ["Restaurants", "New American"] }
  ],
  "phone": "(406) 626-8866",
  "website": { "link": "http://garydanko.com", "display_link": null, "is_verified": false },
  "address": { "line1": "800 N Point St", "city": "San Francisco", "state": "CA", "postal_code": "94109", "country_code": "US" },
  "coordinates": { "latitude": 37.8058724, "longitude": -122.4205943 },
  "hours": { "is_open_now": false, "today": ["5:00 PM - 10:00 PM"] },
  "attributes": { "accepts_apple_pay": true, "parking": ["garage", "street"], "wifi": "free", "alcohol": "full_bar", "attire": "dressy", "takes_reservations": true },
  "health_inspections": [
    { "score": "Pass", "date": "2026-06-04", "provider": { "name": "Health Department Intelligence", "link": "https://hazelanalytics.com/" } }
  ],
  "popular_dishes": [
    { "name": "Roast Maine Lobster", "rating": 4.62, "review_count": 459, "photo_count": 338 }
  ],
  "is_claimed": true
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Yelp Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/yelp-scraper
cd yelp-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/businesses/details?business=gary-danko-san-francisco"
```

```json
{
  "id": "WavvLdfdP6g8aZTtbBQHTw",
  "alias": "gary-danko-san-francisco",
  "name": "Gary Danko",
  "link": "https://www.yelp.com/biz/gary-danko-san-francisco",
  "summary": "Fine dining with customizable menus and a romantic ambiance.",
  "rating": 4.5,
  "review_count": 6150,
  "price_range": "$$$$",
  "phone": "(406) 626-8866",
  "website": { "link": "http://garydanko.com", "display_link": null, "is_verified": false },
  "address": { "line1": "800 N Point St", "city": "San Francisco", "state": "CA", "postal_code": "94109" },
  "coordinates": { "latitude": 37.8058724, "longitude": -122.4205943 },
  "hours": { "is_open_now": false, "today": ["5:00 PM - 10:00 PM"] },
  "popular_dishes": [
    { "name": "Roast Maine Lobster", "rating": 4.62, "review_count": 459 }
  ]
}
```

All 28 endpoints are now live at `http://localhost:8000`.

Search, search filters, menus and related businesses sit behind DataDome. To unlock them, set `YELP_PROXY` (a sticky US residential proxy) and `CAPSOLVER_API_KEY` — see [`config.py`](config.py). Everything else works out of the box.

## 📚 Endpoints

28 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Business Details | `/businesses/details` | Everything about one business in a single call |
| Search / Location Autocomplete | `/search/autocomplete`, `/locations/autocomplete` | Typeahead for searches, businesses and places |
| Search Businesses | `/search` | Yelp's own ranking, 10 per page, with filters |
| Quick Search | `/search/quick` | Up to 25 businesses by name, instantly |
| Search Filters | `/search/filters` | Every filter Yelp offers for a search |
| Categories | `/categories` | All 1,500+ Yelp categories with parents |
| Batch Business Lookup | `/businesses/batch` | 20 businesses in one call |
| Business Reviews | `/businesses/reviews` | Full reviews with 6 sorts, filters and translation |
| Not Recommended Reviews | `/businesses/reviews/not-recommended` | The reviews Yelp's filter hides |
| Review Topics / Reviews by Topic | `/businesses/reviews/topics`, `/businesses/reviews/by-topic` | What reviewers love and hate, with sentiment |
| Review Highlights | `/businesses/reviews/highlights` | The phrases reviewers mention most |
| Business Photos | `/businesses/photos` | Original-size photos and videos by category |
| Popular Dishes | `/businesses/popular-dishes` | Top dishes with ratings, prices and photos |
| Business Menu | `/businesses/menu` | Menu sections, items and prices |
| Business Questions / Answers | `/businesses/questions`, `/businesses/questions/answers` | Community Q&A with every answer |
| Business Posts | `/businesses/posts` | The business's own announcements |
| Related Businesses | `/businesses/related` | Competitors Yelp recommends alongside |
| User Profile | `/users/details` | Elite years, counts, compliments and bio |
| User Reviews / Photos | `/users/reviews`, `/users/photos` | Everything a reviewer wrote and shot |
| User Friends / Following / Compliments | `/users/friends`, `/users/following`, `/users/compliments` | A reviewer's network and fans |
| Search Events / Event Details | `/events/search`, `/events/details` | City events with venue, time and price |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-yelp-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-yelp-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-yelp-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/businesses/details",
    params={"business": "gary-danko-san-francisco"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Yelp Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Yelp%20Scraper%20API.)

[![Ask Us by Email about Yelp Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Yelp%20Scraper%20API&body=I%20need%20help%20using%20the%20Yelp%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/yelp-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/yelp-scraper)
