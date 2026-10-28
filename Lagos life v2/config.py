import os

# Set these in Render's Environment Variables dashboard
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL   = "https://lagoslife.app"

PROXIES = [
    "http://IX5KoU9CiAgvaJ2T:lunatic53_country-us_state-california_session-qXst0fYm_lifetime-24h@geo.iproyal.com:12321",
    "http://IX5KoU9CiAgvaJ2T:lunatic53_country-us_state-california_session-cGbLQuzc_lifetime-24h@geo.iproyal.com:12321",
    "http://IX5KoU9CiAgvaJ2T:lunatic53_country-us_state-california_session-iNBoWgan_lifetime-24h@geo.iproyal.com:12321",
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")
