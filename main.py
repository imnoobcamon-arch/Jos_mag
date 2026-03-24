"""
Telegram Breaking News Bot
Fetches news from BBC, Reuters, and Al Jazeera every hour.
Headline style: Bold Italic Serif (Unicode)
"""

import os
import re
import logging
import asyncio
import feedparser
import hashlib
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler


# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
UPDATE_INTERVAL    = 3600  # 1 hour in seconds

RSS_FEEDS = {
    "BBC News":   "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Reuters":    "https://feeds.reuters.com/reuters/worldNews",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}

# In-memory duplicate tracker
sent_headlines: set = set()

# Track last update time for countdown
last_update_time: datetime = None


# ─────────────────────────────────────────────
# UNICODE FONT HELPERS — Bold Italic Serif
# ─────────────────────────────────────────────
def to_bold_italic(text: str) -> str:
    """
    Convert ASCII letters to Unicode Bold Italic Serif.
    Example: Breaking News → 𝑩𝒓𝒆𝒂𝒌𝒊𝒏𝒈 𝑵𝒆𝒘𝒔
    Digits are converted to bold (no italic digit set in Unicode).
    """
    upper_normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lower_normal = "abcdefghijklmnopqrstuvwxyz"
    digit_normal = "0123456789"

    upper_bi = "𝑨𝑩𝑪𝑫𝑬𝑭𝑮𝑯𝑰𝑱𝑲𝑳𝑴𝑵𝑶𝑷𝑸𝑹𝑺𝑻𝑼𝑽𝑾𝑿𝒀𝒁"
    lower_bi = "𝒂𝒃𝒄𝒅𝒆𝒇𝒈𝒉𝒊𝒋𝒌𝒍𝒎𝒏𝒐𝒑𝒒𝒓𝒔𝒕𝒖𝒗𝒘𝒙𝒚𝒛"
    digit_bd = "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"

    result = ""
    for ch in text:
        if ch in upper_normal:
            result += upper_bi[upper_normal.index(ch)]
        elif ch in lower_normal:
            result += lower_bi[lower_normal.index(ch)]
        elif ch in digit_normal:
            result += digit_bd[digit_normal.index(ch)]
        else:
            result += ch  # punctuation, spaces, symbols pass through unchanged
    return result


def to_bold_sans(text: str) -> str:
    """
    Bold Sans-Serif — used for the bot header title only.
    Keeps the header visually distinct from article headlines.
    Example: The Chronicle → 𝗧𝗵𝗲 𝗖𝗵𝗿𝗼𝗻𝗶𝗰𝗹𝗲
    """
    upper_normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lower_normal = "abcdefghijklmnopqrstuvwxyz"

    upper_bs = "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    lower_bs = "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"

    result = ""
    for ch in text:
        if ch in upper_normal:
            result += upper_bs[upper_normal.index(ch)]
        elif ch in lower_normal:
            result += lower_bs[lower_normal.index(ch)]
        else:
            result += ch
    return result


# ─────────────────────────────────────────────
# NEWS FETCHING
# ─────────────────────────────────────────────
def fetch_feed(source_name: str, feed_url: str) -> list:
    """
    Fetch and parse a single RSS feed.
    Returns a list of article dicts:
      { title, summary, source, published, url, hash }
    """
    try:
        feed = feedparser.parse(feed_url)
        articles = []

        for entry in feed.entries[:10]:
            title   = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            url     = entry.get("link", "")

            # Strip any HTML tags from summary
            summary = re.sub(r"<[^>]+>", "", summary)
            summary = summary[:200] + "..." if len(summary) > 200 else summary

            # Parse published time
            try:
                if entry.get("published_parsed"):
                    pub_dt  = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    pub_str = pub_dt.strftime("%d %b %Y, %H:%M UTC")
                else:
                    pub_str = "Time unavailable"
            except Exception:
                pub_str = "Time unavailable"

            headline_hash = hashlib.md5(title.encode()).hexdigest()

            articles.append({
                "title":     title,
                "summary":   summary,
                "source":    source_name,
                "published": pub_str,
                "url":       url,
                "hash":      headline_hash,
            })

        logger.info(f"Fetched {len(articles)} articles from {source_name}")
        return articles

    except Exception as e:
        logger.error(f"Failed to fetch {source_name}: {e}")
        return []


def fetch_all_news() -> list:
    """
    Fetch from all RSS sources, filter duplicates, return top 5 fresh articles.
    """
    all_articles = []

    for source_name, feed_url in RSS_FEEDS.items():
        articles = fetch_feed(source_name, feed_url)
        for article in articles:
            if article["hash"] not in sent_headlines:
                all_articles.append(article)

    fresh = all_articles[:5]

    # Mark as sent
    for article in fresh:
        sent_headlines.add(article["hash"])

    # Prevent memory bloat — trim oldest hashes beyond 500
    if len(sent_headlines) > 500:
        for h in list(sent_headlines)[:100]:
            sent_headlines.discard(h)

    logger.info(f"Fresh articles to send: {len(fresh)}")
    return fresh


# ─────────────────────────────────────────────
# MESSAGE FORMATTER
# ─────────────────────────────────────────────
def format_countdown() -> str:
    """Return a human-readable countdown to next scheduled update."""
    global last_update_time
    if last_update_time is None:
        return "Next update in: 60m 00s"
    elapsed = (datetime.now(timezone.utc) - last_update_time).total_seconds()
    remain  = max(0, UPDATE_INTERVAL - elapsed)
    mins    = int(remain // 60)
    secs    = int(remain % 60)
    return f"Next update in: {mins}m {secs:02d}s"


def format_message(articles: list) -> str:
    """
    Assemble the full Telegram message.

    Layout:
      ┌─ HEADER  (Bold Sans title + timestamp + countdown) ─┐
      │  NEWS ITEMS  (Bold Italic Serif headlines + body)    │
      └─ FOOTER  (bot signature) ────────────────────────────┘
    """
    now_str = datetime.now(timezone.utc).strftime("%d %b %Y  •  %H:%M UTC")

    if not articles:
        return (
            "⚜️ ══════════════════════════ ⚜️\n"
            f"   {to_bold_sans('The Chronicle Bot')}\n"
            "⚜️ ══════════════════════════ ⚜️\n\n"
            "No new headlines available right now.\n"
            "Check back at the next update.\n\n"
            f"⏱  {format_countdown()}"
        )

    lines = []

    # ── HEADER ──────────────────────────────────────────────
    lines += [
        "⚜️ ══════════════════════════ ⚜️",
        f"     {to_bold_sans('The Daily Chronicle')}",
        f"     {to_bold_sans('Breaking World News')}",
        "⚜️ ══════════════════════════ ⚜️",
        f"🗓   {now_str}",
        f"⏱   {format_countdown()}",
        "",
    ]

    # ── NEWS ITEMS ───────────────────────────────────────────
    for i, art in enumerate(articles, start=1):
        lines += [
            "─────────────────────────────",
            f"[{i}]  {to_bold_italic(art['title'])}",       # ← Bold Italic Serif headline
            "",
            f"{art['summary']}",                             # plain readable body
            "",
            f"🏛  {art['source']}",
            f"🕰  {art['published']}",
            f"🔗  {art['url']}",
            "",
        ]

    # ── FOOTER ───────────────────────────────────────────────
    lines += [
        "─────────────────────────────",
        "⚜️ ══════════════════════════ ⚜️",
        f"   {to_bold_sans('Powered by The Chronicle Bot')}",
        "⚜️ ══════════════════════════ ⚜️",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# TELEGRAM SENDER
# ─────────────────────────────────────────────
async def send_news(bot: Bot) -> None:
    """Fetch, format, and send the hourly news digest."""
    global last_update_time
    logger.info("Running scheduled news update...")

    articles = fetch_all_news()
    message  = format_message(articles)

    # Split if message exceeds Telegram's 4096-char limit
    chunks = [message[i:i + 4096] for i in range(0, len(message), 4096)]

    try:
        for chunk in chunks:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=chunk,
                parse_mode=None,                    # plain text keeps Unicode intact
                disable_web_page_preview=True,
            )
            await asyncio.sleep(0.5)

        last_update_time = datetime.now(timezone.utc)
        logger.info("News update sent successfully.")

    except TelegramError as e:
        logger.error(f"Telegram send error: {e}")
    except Exception as e:
        logger.error(f"Unexpected send error: {e}")


# ─────────────────────────────────────────────
# STARTUP MESSAGE
# ─────────────────────────────────────────────
async def send_startup_message(bot: Bot) -> None:
    """Send a one-time online notification when the bot starts."""
    text = (
        "⚜️ ══════════════════════════ ⚜️\n"
        f"   {to_bold_sans('The Chronicle Bot')}\n"
        "⚜️ ══════════════════════════ ⚜️\n\n"
        "✅  Bot is ONLINE and running.\n"
        "📡  Sources: BBC News  •  Reuters  •  Al Jazeera\n"
        "🕐  Automatic updates every 1 hour.\n\n"
        "First dispatch arriving shortly...\n\n"
        "⚜️ ══════════════════════════ ⚜️"
    )
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            disable_web_page_preview=True,
        )
        logger.info("Startup message sent.")
    except TelegramError as e:
        logger.error(f"Startup message failed: {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
async def main() -> None:
    """Boot the bot, schedule hourly updates, and keep the loop alive."""

    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set. Exiting.")
        return
    if not TELEGRAM_CHAT_ID:
        logger.critical("TELEGRAM_CHAT_ID not set. Exiting.")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Validate token
    try:
        me = await bot.get_me()
        logger.info(f"Authenticated as @{me.username}")
    except TelegramError as e:
        logger.critical(f"Invalid bot token: {e}")
        return

    await send_startup_message(bot)
    await send_news(bot)          # immediate first dispatch

    # Hourly scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        send_news,
        trigger="interval",
        seconds=UPDATE_INTERVAL,
        args=[bot],
        id="hourly_news",
        name="Hourly News Dispatch",
        max_instances=1,
    )
    scheduler.start()
    logger.info(f"Scheduler started. Next dispatch in {UPDATE_INTERVAL // 60} minutes.")

    # Keep the event loop alive
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
