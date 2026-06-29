# Yelp Scraper API

Search Yelp businesses by location and pull full profiles — ratings, hours, photos, contact info, and review highlights — via a simple REST API. 25 free requests/month.

## Key Features

- Search Yelp businesses by location and pull full business profiles with hours, photos, contact info, and review highlights — all via 1 API.
- 25 free queries per month. No credit card required.

Here's a sample response for a **single business** from the search results:
```json
{
  "name": "Computer Concepts",
  "business_id": "computer-concepts-bothell",
  "business_key": "H1kYTl9dsjfMqy6ZKAwdyA",
  "yelp_url": "https://www.yelp.com/biz/computer-concepts-bothell?osq=computer+shop",
  "image": "https://s3-media0.fl.yelpcdn.com/bphoto/2glghkleMgFizKwdAc23jg/ls.jpg",
  "avg_rating": 4.8,
  "review_count": 155,
  "categories": [
    {
      "name": "IT Services & Computer & Laptop Repair",
      "url": "https://www.yelp.com/search?find_desc=IT+Services+%26+Computer+%26+Laptop+Repair&find_loc=Seattle%2C+WA"
    },
    {
      "name": "Computers",
      "url": "https://www.yelp.com/search?find_desc=Computers&find_loc=Seattle%2C+WA"
    }
  ],
  "summary": "The only computer shop I have and will ever grace with my patronage. Been a returning customer my..."
}
```

## ▶️ Video Tutorial

Watch the complete API walkthrough:

[![Yelp Scraper API Walkthrough](https://raw.githubusercontent.com/omkarcloud/yelp-scraper/master/yelp-scraper-youtube-video-preview.png)](https://www.youtube.com/watch?v=fE3jYQwRE0g)

## Get API Key

Create an account at [omkar.cloud](https://www.omkar.cloud/auth/sign-up?redirect=/api-key) to get your API key.

It takes just 2 minutes to sign up. You get 25 free requests every month for detailed Yelp data.

This is a well built product, and your search for the best Yelp Scraper API ends right here.


## Quick Start

```bash
curl -X GET "https://yelp-scraper.omkar.cloud/yelp/businesses/search?search_location=Seattle,%20WA&search_term=computer%20shop" \
  -H "API-Key: YOUR_API_KEY"
```

```json
{
  "result_count": 10,
  "result_offset": 0,
  "next": "https://yelp-scraper.omkar.cloud/yelp/businesses/search?search_location=Seattle%2C+WA&search_term=computer+shop&result_offset=10",
  "previous": null,
  "businesses": [
    {
      "name": "Computer Concepts",
      "business_id": "computer-concepts-bothell",
      "yelp_url": "https://www.yelp.com/biz/computer-concepts-bothell?osq=computer+shop",
      "image": "https://s3-media0.fl.yelpcdn.com/bphoto/2glghkleMgFizKwdAc23jg/ls.jpg",
      "avg_rating": 4.8,
      "review_count": 155,
      "summary": "The only computer shop I have and will ever grace with my patronage. Been a returning customer my..."
    }
  ]
}
```

## Quick Start (Python)

```bash
pip install requests
```

```python
import requests

response = requests.get(
    "https://yelp-scraper.omkar.cloud/yelp/businesses/search",
    params={"search_location": "Seattle, WA", "search_term": "computer shop"},
    headers={"API-Key": "YOUR_API_KEY"}
)

print(response.json())
```


## API Reference

### Search Local Businesses

```
GET https://yelp-scraper.omkar.cloud/yelp/businesses/search
```

#### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `search_location` | Yes | — | City, full address, neighborhood, or ZIP code (e.g. `Seattle, WA` or `94103`). |
| `search_term` | No | — | Free-text keyword: cuisine, business name, or service (e.g. `coffee`, `plumber`, `tacos`). |
| `sort_order` | No | `best_match` | `best_match`, `top_rated`, `most_reviewed` |
| `result_offset` | No | `0` | Zero-based offset for pagination. Use `0`, `10`, `20`, ... |

#### Example

```python
import requests

response = requests.get(
    "https://yelp-scraper.omkar.cloud/yelp/businesses/search",
    params={
        "search_location": "Seattle, WA",
        "search_term": "computer shop",
    },
    headers={"API-Key": "YOUR_API_KEY"}
)

print(response.json())
```

#### Response

<details>
<summary>Sample Response (click to expand)</summary>

```json
{
  "result_count": 10,
  "result_offset": 0,
  "next": "https://yelp-scraper.omkar.cloud/yelp/businesses/search?search_location=Seattle%2C+WA&search_term=computer+shop&result_offset=10",
  "previous": null,
  "businesses": [
    {
      "name": "Computer Concepts",
      "business_id": "computer-concepts-bothell",
      "business_key": "H1kYTl9dsjfMqy6ZKAwdyA",
      "yelp_url": "https://www.yelp.com/biz/computer-concepts-bothell?osq=computer+shop",
      "image": "https://s3-media0.fl.yelpcdn.com/bphoto/2glghkleMgFizKwdAc23jg/ls.jpg",
      "avg_rating": 4.8,
      "review_count": 155,
      "categories": [
        {
          "name": "IT Services & Computer & Laptop Repair",
          "url": "https://www.yelp.com/search?find_desc=IT+Services+%26+Computer+%26+Laptop+Repair&find_loc=Seattle%2C+WA"
        },
        {
          "name": "Computers",
          "url": "https://www.yelp.com/search?find_desc=Computers&find_loc=Seattle%2C+WA"
        },
        {
          "name": "Electrical Repairs",
          "url": "https://www.yelp.com/search?find_desc=Electrical+Repairs&find_loc=Seattle%2C+WA"
        }
      ],
      "summary": "The only computer shop I have and will ever grace with my patronage. Been a returning customer my..."
    },
    {
      "name": "NerdsToGo - Bellevue",
      "business_id": "nerdstogo-bellevue-bellevue",
      "business_key": "TVH0Lpf2d9y4P-pJCGlSmA",
      "yelp_url": "https://www.yelp.com/biz/nerdstogo-bellevue-bellevue?osq=computer+shop",
      "image": "https://s3-media0.fl.yelpcdn.com/bphoto/VT0CeujomzY5n5j0CnWYPQ/ls.jpg",
      "avg_rating": 4.7,
      "review_count": 75,
      "categories": [
        {
          "name": "IT Services & Computer & Laptop Repair",
          "url": "https://www.yelp.com/search?find_desc=IT+Services+%26+Computer+%26+Laptop+Repair&find_loc=Seattle%2C+WA"
        }
      ],
      "summary": "Most recently, I took my computer to the GeekSquad at Best Buy and they diagnosed my keyboard issue..."
    }
  ],
  "sponsored_businesses": [
    {
      "name": "Hebert Service",
      "business_id": "hebert-service-kirkland",
      "business_key": "NcGSjPpqtWHRTURcNQFcww",
      "avg_rating": 5.0,
      "review_count": 3,
      "categories": [
        {
          "name": "Mobile Phone Repair",
          "url": "https://www.yelp.com/search?find_desc=Mobile+Phone+Repair&find_loc=Seattle%2C+WA"
        }
      ],
      "summary": "I highly recommend Hebert for any sort of device repair. He does extremely quick and quality work..."
    }
  ],
  "available_filters": {
    "price_options": [
      { "label": "$", "value": "RestaurantsPriceRange2.1" },
      { "label": "$$", "value": "RestaurantsPriceRange2.2" },
      { "label": "$$$", "value": "RestaurantsPriceRange2.3" },
      { "label": "$$$$", "value": "RestaurantsPriceRange2.4" }
    ],
    "category_options": [
      { "label": "Computers", "value": "computers" },
      { "label": "IT Services & Computer & Laptop Repair", "value": "itservices" },
      { "label": "Mobile Phone Repair", "value": "mobilephonerepair" }
    ],
    "distance_options": [
      { "label": "Within 1 mile", "value": "g:-122.348,47.616,-122.322,47.634" },
      { "label": "Within 5 miles", "value": "g:-122.386,47.590,-122.284,47.660" }
    ]
  }
}
```

</details>

---

### Get Business Details

```
GET https://yelp-scraper.omkar.cloud/yelp/businesses/details
```

#### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `business_id` | Yes | — | Yelp business alias (e.g. `computer-concepts-bothell`). Get it from the `business_id` field returned by Search Local Businesses. |

#### Example

```python
import requests

response = requests.get(
    "https://yelp-scraper.omkar.cloud/yelp/businesses/details",
    params={"business_id": "computer-concepts-bothell"},
    headers={"API-Key": "YOUR_API_KEY"}
)

print(response.json())
```

#### Response Fields

Returns the full Yelp business profile including name, about, ratings, claim status, categories, full contact block (phone, website, address, directions, map image), every photo, business history, full weekly operating hours with `currently_open` flags and special holiday hours, features list (wheelchair accessible, payment methods, dogs allowed, etc.), popular items, ambiance highlights, review highlights with top keywords, menu links, and community Q&A.

<details>
<summary>Sample Response (click to expand)</summary>

```json
{
  "name": "Computer Concepts",
  "business_id": "computer-concepts-bothell",
  "business_key": "H1kYTl9dsjfMqy6ZKAwdyA",
  "about": "We specialize in: Computer Repair (Desktops & Laptops), PC Recycling, Small Business IT Consulting, Onsite & Remote Services. We have six experienced technicians on staff, and you can speak directly with the one working on your device...",
  "avg_rating": 4.8,
  "review_count": 155,
  "is_claimed": true,
  "categories": [
    {
      "name": "IT Services & Computer & Laptop Repair",
      "url": "https://www.yelp.com/search?find_desc=IT+Services+%26+Computer+%26+Laptop+Repair&find_loc=Bothell%2C+WA"
    },
    {
      "name": "Computers",
      "url": "https://www.yelp.com/search?find_desc=Computers&find_loc=Bothell%2C+WA"
    },
    {
      "name": "Electrical Repairs",
      "url": "https://www.yelp.com/search?find_desc=Electrical+Repairs&find_loc=Bothell%2C+WA"
    }
  ],
  "contact": {
    "phone": "(425) 481-3666",
    "website": "https://computerconceptsbothell.com",
    "address": "17624 15th Ave SE Ste 113A Bothell, WA 98012 United States",
    "directions_url": "https://www.yelp.co.nz/map/H1kYTl9dsjfMqy6ZKAwdyA",
    "map_image": "https://maps.googleapis.com/maps/api/staticmap?size=315x180&...",
    "country": "US"
  },
  "images": [
    "https://s3-media0.fl.yelpcdn.com/bphoto/2glghkleMgFizKwdAc23jg/l.jpg",
    "https://s3-media0.fl.yelpcdn.com/bphoto/8gjutqbD818Wkl2JnvchnA/l.jpg",
    "https://s3-media0.fl.yelpcdn.com/bphoto/k6E8YfIdTzVt9xQxEyWXXg/l.jpg"
  ],
  "all_images_url": "https://www.yelp.com/biz_photos/computer-concepts-bothell",
  "history": {
    "summary": "Originally searching in North Seattle, Robin's friend suggested checking out Mill Creek. After several overpriced showings, their agent mentioned a spot in Bothell...",
    "established": "1990"
  },
  "operating_hours": {
    "schedule": [
      { "day": "Mon", "hours": "9:00 AM - 6:00 PM", "currently_open": false },
      { "day": "Tue", "hours": "9:00 AM - 6:00 PM" },
      { "day": "Wed", "hours": "9:00 AM - 6:00 PM" },
      { "day": "Thu", "hours": "9:00 AM - 6:00 PM" },
      { "day": "Fri", "hours": "9:00 AM - 6:00 PM" },
      { "day": "Sat", "hours": "9:00 AM - 6:00 PM" },
      { "day": "Sun", "hours": "Closed" }
    ]
  },
  "features": [
    { "name": "Wheelchair accessible", "is_active": true },
    { "name": "Accepts Apple Pay", "is_active": true },
    { "name": "Accepts credit cards", "is_active": true },
    { "name": "Dogs allowed", "is_active": true },
    { "name": "Offers military discount", "is_active": true }
  ],
  "review_highlights": [
    {
      "keyword": "gaming PC",
      "snippet": "Finally decided to buy a gaming PC after many years of struggling with the pricing on many of the PC components.",
      "author": "Jason S.",
      "mentions_count": 5,
      "url": "https://www.yelp.com/biz/computer-concepts-bothell?hrid=j_B1RXFr4uBMGbXnd3oMYA&rh_ident=gaming_pc&rh_type=phrase"
    },
    {
      "keyword": "desktop",
      "snippet": "The NEXT day they called and the work order was complete and the desktop works better than new!!!",
      "author": "Del M.",
      "mentions_count": 7,
      "url": "https://www.yelp.com/biz/computer-concepts-bothell?hrid=4U_cW2zNNTnMXQGngjM_iQ&rh_ident=desktop&rh_type=phrase"
    }
  ],
  "menu_url": "https://www.yelp.com/menu/computer-concepts-bothell",
  "community_questions": [
    {
      "question": "Hi, do you buy Dell 23\" monitors? Mine is in great condition (HDMI/VGA).",
      "answer": "Sometimes, can I ask what model Dell 23 inch monitor?",
      "author": "Will R.",
      "asked_on": "2025-12-24T04:00:33Z",
      "helpful_votes": 0
    }
  ],
  "more_questions_url": "https://www.yelp.com/questions/H1kYTl9dsjfMqy6ZKAwdyA"
}
```

</details>

## Error Handling

```python
response = requests.get(
    "https://yelp-scraper.omkar.cloud/yelp/businesses/search",
    params={"search_location": "Seattle, WA"},
    headers={"API-Key": "YOUR_API_KEY"}
)

if response.status_code == 200:
    data = response.json()
elif response.status_code == 401:
    # Invalid API key
    pass
elif response.status_code == 429:
    # Rate limit exceeded
    pass
```

## FAQs

### What data does the API return?

**Search Local Businesses** returns per business:
- Name, Yelp URL, business ID (alias), internal business key
- Average rating, review count, price tier
- Thumbnail image and snippet from a top review
- Full list of Yelp categories with links
- Neighborhood, phone number (when listed)
- Service options: delivery, takeout, outdoor seating
- Highlights (e.g. "Recently opened", "Locally owned")
- Sponsored/ad results in a separate `sponsored_businesses` array
- Filter options Yelp offers for the search (price, category, distance, features)
- Pagination: `result_count`, `result_offset`, `next`, `previous`

**Get Business Details** returns per business:
- Name, business ID, internal key, "about" description
- Average rating, review count, price tier, claim status
- All categories with Yelp search links
- Contact block: phone, website, address, cross streets, neighborhoods, country, directions URL, map preview image
- Every photo Yelp has on file, plus the link to view all photos
- Business history: summary text and year established
- Full weekly hours with `currently_open` flag and special holiday hours
- Features list (wheelchair accessible, Apple Pay, dogs allowed, military discount, etc.) — each with `is_active`
- Popular items (name, photo count, mention count, thumbnail)
- Ambiance: tagged photo galleries plus highlight tags ("Casual", "Moderate noise")
- Review highlights: top keywords from reviews with author, snippet, and mention count
- Menu URL and website menu URL when available
- Community Q&A: question, answer, author, date, helpful votes
- Health inspection score and provider (where Yelp surfaces it)
- Business alert (e.g. "Temporarily closed")


All in structured JSON. Ready to use in your app.

### How accurate is the data?

Data is pulled from Yelp in real time. Every API call fetches live data — not cached or stale results. Ratings, hours, photos, and contact info reflect what's on Yelp right now.

### How do I get a business_id to call the Details endpoint?

Hit the Search Local Businesses endpoint first. Every business in the response has a `business_id` field (e.g. `computer-concepts-bothell`) — pass that straight into the Details endpoint.

If you already have a Yelp business URL like `https://www.yelp.com/biz/computer-concepts-bothell`, the last path segment is the `business_id`.

### How does pagination work?

Yelp returns 10 businesses per page. Pagination is offset-based, not page-based.

- `result_offset=0` returns businesses 1–10 (the default).
- `result_offset=10` returns businesses 11–20.
- `result_offset=20` returns businesses 21–30.

The response includes `next` and `previous` fields with ready-to-call URLs, so you don't have to compute offsets yourself.

### Can I sort the results?

Yes. Pass `sort_order` with one of three values:

- `best_match` — Yelp's default ranking.
- `top_rated` — Highest star rating first.
- `most_reviewed` — Largest review count first.

### Does the API return sponsored / ad businesses?

Yes — separately. Organic results go in `businesses` and Yelp's paid placements go in `sponsored_businesses`. You can render them, filter them out, or use them for ad-monitoring use cases.

## Rate Limits

| Plan | Price | Requests/Month |
|------|-------|----------------|
| Free | $0 | 25 |
| Starter | $16 | 800 |
| Grow | $48 | 2,400 |
| Scale | $148 | 7,400 |

## Questions? We have answers.

Reach out anytime. We will solve your query within 1 working day.

[![Contact Us on WhatsApp about Yelp Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20have%20a%20question%20about%20the%20Yelp%20Scraper%20API.)

[![Contact Us on Email about Yelp Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Yelp%20Scraper%20API%20Question)
