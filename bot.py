import discord
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime, timezone
import re
import cloudscraper
from bs4 import BeautifulSoup
from flask import Flask
import threading
import urllib.parse

# -------------------------
# Flask keep-alive (Render)
# -------------------------
app = Flask(__name__)
@app.route("/")
def home():
    return "discord bot running"

def run_web():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web, daemon=True).start()

# -------------------------
# Discord setup
# -------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

MAX_CONCURRENT = 5
scrape_queue = asyncio.Queue()
active_scrapes = 0
user_credits = {}

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)

# -------------------------
# Helpers: build / search URLs
# -------------------------
def slug(x):
    return x.strip().replace(" ", "-")

def build_album_candidates(raw):
    """
    raw: 'Artist - Album' expected but we'll still try to be flexible.
    returns list of candidate album URLs (most likely first).
    """
    candidates = []

    # try to split properly
    if " - " in raw:
        artist, album = raw.split(" - ", 1)
        a = slug(artist)
        b = slug(album)
        candidates += [
            f"https://genius.com/albums/{a.title()}/{b.title()}",
            f"https://genius.com/albums/{a}/{b}",
            f"https://genius.com/albums/{a.lower()}/{b.lower()}",
        ]
    else:
        # If no " - ", try permutations
        parts = raw.strip().split()
        if len(parts) >= 2:
            # assume last word(s) are album
            for split_at in range(1, len(parts)):
                artist = " ".join(parts[:split_at])
                album = " ".join(parts[split_at:])
                a = slug(artist); b = slug(album)
                candidates += [
                    f"https://genius.com/albums/{a.title()}/{b.title()}",
                    f"https://genius.com/albums/{a}/{b}",
                ]

    # ensure uniqueness while preserving order
    seen = set()
    uniq = []
    for u in candidates:
        if u not in seen:
            uniq.append(u); seen.add(u)
    return uniq

def search_genius_album(raw):
    """
    Fallback: use Genius search to locate album result and return its albums/... link if found.
    """
    q = urllib.parse.quote_plus(raw)
    url = f"https://genius.com/search?q={q}"
    try:
        r = scraper.get(url, timeout=30)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # search results contain links; look for /albums/ links
        for a in soup.select("a[href]"):
            href = a["href"]
            if "/albums/" in href:
                # normalize absolute
                if href.startswith("/"):
                    href = "https://genius.com" + href
                return href
    except Exception as e:
        print("DEBUG search_genius_album error:", e)
    return None

# -------------------------
# Parser: producers
# -------------------------
def parse_producers(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # 1) metadata_unit (album-level)
    for unit in soup.select("div.metadata_unit"):
        label = unit.select_one("h3, .metadata_unit-label, .metadata_label")
        if label and "producer" in label.get_text(" ", strip=True).lower():
            for a in unit.select("a"):
                name = a.get_text(strip=True)
                if name:
                    username = re.sub(r"[^a-z0-9]", "", name.lower())
                    ig = username if len(username) > 2 else "unknown"
                    results.append(f"**{name}** → @{ig}")

    # 2) per-song credits (song rows)
    # pick multiple possible selectors (Genius layout varies)
    song_rows = soup.select("div.chart_row, div.song_row, li.song, div.track_listing_row")
    for row in song_rows:
        title_tag = row.select_one(".chart_row-content-title, .song_title, .song_title_raw, .title")
        if not title_tag:
            continue
        title = title_tag.get_text(" ", strip=True)[:50]
        producers = set()
        # check blocks that might contain roles/credits
        for block in row.select(".metadata_unit, .SongInfo, .ContributorList, .credits, .roles"):
            txt = block.get_text(" ", strip=True).lower()
            if "producer" in txt or "prod" in txt:
                for a in block.select('a[href^="/artists/"], a[href*="/artist/"], a'):
                    pname = a.get_text(strip=True)
                    if pname:
                        producers.add(pname)
        # fallback: find any "producer" words and take sibling links
        if not producers:
            # look for text matches "Produced by <link>"
            txt = row.get_text(" ", strip=True)
            m = re.search(r"Produced by (.+)", txt, re.IGNORECASE)
            if m:
                # try to extract names separated by commas
                names = [n.strip() for n in re.split(r",|&| and ", m.group(1)) if n.strip()]
                for n in names:
                    producers.add(n)

        for p in producers:
            username = re.sub(r"[^a-z0-9]", "", p.lower())
            ig = username if len(username) > 2 else "unknown"
            results.append(f"`{title:<40}` → **{p}** @{ig}")

    # dedupe while preserving order
    seen = set(); out = []
    for r in results:
        if r not in seen:
            out.append(r); seen.add(r)
    return out

# -------------------------
# Main runner
# -------------------------
async def run_scrape(ctx, album):
    global active_scrapes
    uid = ctx.author.id
    user_credits[uid] = user_credits.get(uid, 100)

    if user_credits[uid] <= 0:
        await ctx.send("Geen credits meer → koop Producer Pass")
        active_scrapes -= 1
        return

    user_credits[uid] -= 1
    status_msg = await ctx.send(f"Scraping **{album}**… (probeer URLs + zoek fallback)")

    candidates = build_album_candidates(album)
    print("DEBUG candidates:", candidates)
    html = None
    used_url = None

    # Try direct album candidate URLs
    for url in candidates:
        try:
            r = scraper.get(url, timeout=30)
            print(f"DEBUG try {url} → {r.status_code} len {len(r.text) if r and r.text else 0}")
            if r.status_code == 200 and len(r.text) > 1500:
                html = r.text
                used_url = url
                break
        except Exception as e:
            print("DEBUG request error:", e)

    # Fallback: Genius search page
    if not html:
        search_url = search_genius_album(album)
        print("DEBUG search_url:", search_url)
        if search_url:
            try:
                r = scraper.get(search_url, timeout=30)
                if r.status_code == 200 and len(r.text) > 1500:
                    html = r.text
                    used_url = search_url
            except Exception as e:
                print("DEBUG fallback request error:", e)

    if not html:
        await status_msg.edit(content="Album niet gevonden. Gebruik **Artist - Album**. (Debug logs in console)")
        active_scrapes -= 1
        return

    # parse
    results = parse_producers(html)
    print("DEBUG parsed results count:", len(results))

    if not results:
        results = ["Geen producers gevonden op deze pagina. Zie console-log voor HTML snippet."]

    # embeds
    pages = []
    for i in range(0, len(results), 20):
        embed = discord.Embed(
            title=f"Producers + Instagram – {album}",
            description="\n".join(results[i:i+20]),
            color=0x00ff00,
            timestamp=datetime.now(timezone.utc)
        )
        total = (len(results) - 1) // 20 + 1
        embed.set_footer(text=f"Pagina {i//20 + 1}/{total} • Credits: {user_credits[uid]}")
        pages.append(embed)

    await status_msg.edit(content=f"**Klaar!** {len(results)} producers gevonden (gebruikt: {used_url})")
    msg = await ctx.send(embed=pages[0])

    # paginator
    if len(pages) > 1:
        await msg.add_reaction("◀️")
        await msg.add_reaction("▶️")
        page = 0
        def check(r, u):
            return u == ctx.author and r.message.id == msg.id and str(r.emoji) in ["◀️", "▶️"]
        while True:
            try:
                r, _ = await bot.wait_for("reaction_add", timeout=150, check=check)
                if str(r.emoji) == "▶️" and page < len(pages)-1:
                    page += 1
                elif str(r.emoji) == "◀️" and page > 0:
                    page -= 1
                await msg.edit(embed=pages[page])
                await msg.remove_reaction(r, ctx.author)
            except asyncio.TimeoutError:
                await msg.clear_reactions()
                break

    active_scrapes -= 1

# -------------------------
# Commands & worker
# -------------------------
@bot.command()
async def scrape(ctx, *, album: str):
    await scrape_queue.put((ctx, album))
    await ctx.send(f"In queue – positie {scrape_queue.qsize()} (format: Artist - Album)")

@bot.command()
async def credits(ctx):
    await ctx.send(f"Je hebt **{user_credits.get(ctx.author.id, 0)}** credits.")

@tasks.loop(seconds=2)
async def worker():
    global active_scrapes
    while not scrape_queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album = await scrape_queue.get()
        active_scrapes += 1
        asyncio.create_task(run_scrape(ctx, album))

@bot.event
async def on_ready():
    print(f"{bot.user} is online")
    worker.start()

bot.run(os.getenv("DISCORD_TOKEN"))
