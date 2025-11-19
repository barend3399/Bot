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

# ==============================
# FLASK KEEP-ALIVE SERVER
# ==============================

app = Flask(__name__)

@app.route("/")
def home():
    return "discord bot running"

def run_web():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web).start()


# ==============================
# DISCORD BOT SETUP
# ==============================

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


# ==============================
# UTIL: BUILD GENIUS URLS
# ==============================

def build_album_urls(raw):
    """Verwacht: 'Artist - Album'"""
    if " - " not in raw:
        return []

    artist, album = raw.split(" - ", 1)

    def slug(x):
        return x.strip().replace(" ", "-")

    a = slug(artist)
    b = slug(album)

    return [
        f"https://genius.com/albums/{a.title()}/{b.title()}",
        f"https://genius.com/albums/{a}/{b}",
        f"https://genius.com/albums/{a.lower()}/{b.lower()}",
    ]


# ==============================
# SCRAPER: PARSE PRODUCERS
# ==============================

def parse_producers(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # ====== 1) Pak album metadata (Producer-veld) ======
    metadata_units = soup.select("div.metadata_unit")

    for unit in metadata_units:
        label = unit.select_one("h3.metadata_unit-label")
        if not label:
            continue

        if "producer" in label.get_text(strip=True).lower():
            for a in unit.select("a"):
                name = a.get_text(strip=True)
                username = re.sub(r"[^a-z0-9]", "", name.lower())
                ig = username if len(username) > 2 else "unknown"
                results.append(f"**{name}** → @{ig}")

    # ====== 2) Pak song-per-song producer credit ======
    songs = soup.select("div.chart_row, div.song_row")

    for row in songs:
        title_tag = row.select_one(".chart_row-content-title, .song_title")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)[:50]

        producers = set()

        # Nieuwe Genius layout
        for block in row.select(".metadata_unit, .SongInfo, .RoleLabel, .ContributorList"):
            txt = block.get_text(" ", strip=True).lower()

            if "producer" in txt:
                for a in block.select('a[href^="/artists/"]'):
                    pname = a.get_text(strip=True)
                    producers.add(pname)

        for p in producers:
            username = re.sub(r"[^a-z0-9]", "", p.lower())
            ig = username if len(username) > 2 else "unknown"
            results.append(f"`{title:<40}` → **{p}** @{ig}")

    return results


# ==============================
# MAIN SCRAPE RUNNER
# ==============================

async def run_scrape(ctx, album):
    global active_scrapes
    uid = ctx.author.id
    user_credits[uid] = user_credits.get(uid, 100)

    if user_credits[uid] <= 0:
        await ctx.send("Geen credits meer → koop Producer Pass")
        active_scrapes -= 1
        return

    user_credits[uid] -= 1
    status_msg = await ctx.send(f"Scraping **{album}**… (15–30 sec)")

    urls = build_album_urls(album)
    valid_html = None
    used_url = None

    for url in urls:
        try:
            r = scraper.get(url, timeout=40)
            if r.status_code == 200 and len(r.text) > 2000:
                valid_html = r.text
                used_url = url
                break
        except:
            pass

    if not valid_html:
        await status_msg.edit(
            content="Album niet gevonden. Gebruik **Artist - Album**.\n"
                    "Bijv: `Travis Scott - Astroworld`"
        )
        active_scrapes -= 1
        return

    results = parse_producers(valid_html)

    if not results:
        results = ["Geen producers gevonden op deze pagina."]

    # ==============================
    # EMBEDS PAGINATION
    # ==============================

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

    await status_msg.edit(content=f"**Klaar!** {len(results)} producers gevonden")

    msg = await ctx.send(embed=pages[0])

    if len(pages) > 1:
        await msg.add_reaction("◀️")
        await msg.add_reaction("▶️")
        page = 0

        def check(r, u):
            return (
                u == ctx.author
                and r.message.id == msg.id
                and str(r.emoji) in ["◀️", "▶️"]
            )

        while True:
            try:
                r, _ = await bot.wait_for("reaction_add", timeout=150, check=check)
                if str(r.emoji) == "▶️" and page < len(pages) - 1:
                    page += 1
                elif str(r.emoji) == "◀️" and page > 0:
                    page -= 1

                await msg.edit(embed=pages[page])
                await msg.remove_reaction(r, ctx.author)

            except asyncio.TimeoutError:
                await msg.clear_reactions()
                break

    active_scrapes -= 1


# ==============================
# QUEUE COMMANDS
# ==============================

@bot.command()
async def scrape(ctx, *, album: str):
    await scrape_queue.put((ctx, album))
    await ctx.send(f"In queue – positie {scrape_queue.qsize()} (format: Artist - Album)")


@bot.command()
async def credits(ctx):
    await ctx.send(f"Je hebt **{user_credits.get(ctx.author.id, 0)}** credits.")


# ==============================
# RUN WORKER + BOT
# ==============================

@tasks.loop(seconds=2)
async def worker():
    global active_scrapes
    while not scrape_queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album = await scrape_queue.get()
        active_scrapes += 1
        asyncio.create_task(run_scrape(ctx, album))

bot.run(os.getenv("DISCORD_TOKEN"))
