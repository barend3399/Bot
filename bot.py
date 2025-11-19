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

# =========================
# FLASK KEEP-ALIVE SERVER
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web).start()


# =========================
# DISCORD BOT SETUP
# =========================

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


# =========================
# ON READY
# =========================

@bot.event
async def on_ready():
    print(f"{bot.user} is online — scraper ready")
    worker.start()


# =========================
# QUEUE WORKER
# =========================

@tasks.loop(seconds=2)
async def worker():
    global active_scrapes
    while not scrape_queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album = await scrape_queue.get()
        active_scrapes += 1
        asyncio.create_task(run_scrape(ctx, album))


# =========================
# GENIUS URL BUILDER
# =========================

def build_album_urls(raw):
    """Verwacht: 'Artist - Album' en maakt verschillende Genius URL's."""
    if " - " not in raw:
        return []

    artist, album = raw.split(" - ", 1)
    a = artist.strip().replace(" ", "-")
    b = album.strip().replace(" ", "-")

    urls = [
        f"https://genius.com/albums/{a.title()}/{b.title()}",
        f"https://genius.com/albums/{a}/{b}",
        f"https://genius.com/albums/{a.lower()}/{b.lower()}",
    ]
    return urls


# =========================
# PRODUCER SCRAPER
# =========================

def parse_producers(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Veel stabielere selector:
    songs = soup.select("div.chart_row, div.song_row")

    for row in songs:
        title_tag = row.select_one(".chart_row-content-title, .song_title")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)[:50]

        # Nieuwe Genius layout gebruikt: .RoleLabel + .ContributorList
        producers = []

        # Zoek ALLE rollen
        roles = row.select(".SongInfo, .role_details, .ContributorList")

        for r in roles:
            role_name = r.get_text(" ", strip=True).lower()

            # Als dit een rol is die producer aangeeft
            if any(x in role_name for x in ["producer", "prod", "prod."]):
                for a in r.select('a[href^="/artists/"]'):
                    name = a.get_text(strip=True)
                    if name not in producers:
                        producers.append(name)

        if not producers:
            continue

        # Instagram-guessing (placeholder)
        for p in producers:
            clean = re.sub(r"[^a-z0-9]", "", p.lower())
            ig = clean if len(clean) > 3 else "unknown"
            results.append(f"`{title:<40}` → **{p}** @{ig}")

    return results


# =========================
# SCRAPER RUN
# =========================

async def run_scrape(ctx, album):
    global active_scrapes
    uid = ctx.author.id
    user_credits[uid] = user_credits.get(uid, 100)

    if user_credits[uid] <= 0:
        await ctx.send("Geen credits → upgrade naar Producer Pass!")
        active_scrapes -= 1
        return

    user_credits[uid] -= 1
    status_msg = await ctx.send(f"Scraping **{album}**… (20–45 sec)")

    urls = build_album_urls(album)
    valid_html = None

    for url in urls:
        try:
            r = scraper.get(url, timeout=40)
            if r.status_code == 200 and len(r.text) > 5000:
                valid_html = r.text
                break
        except:
            pass

    if not valid_html:
        await status_msg.edit(content=f"Album niet gevonden. Probeer: `Artist - Album`")
        active_scrapes -= 1
        return

    results = parse_producers(valid_html)

    if not results:
        results = ["Geen producers gevonden op deze album pagina."]

    # =========================
    # EMBEDS PAGINATION
    # =========================

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
    message = await ctx.send(embed=pages[0])

    # Paginate
    if len(pages) > 1:
        await message.add_reaction("◀️")
        await message.add_reaction("▶️")
        page = 0

        def check(r, u):
            return u == ctx.author and r.message.id == message.id and str(r.emoji) in ["◀️", "▶️"]

        while True:
            try:
                r, _ = await bot.wait_for("reaction_add", timeout=180, check=check)
                if str(r.emoji) == "▶️" and page < len(pages) - 1:
                    page += 1
                elif str(r.emoji) == "◀️" and page > 0:
                    page -= 1
                await message.edit(embed=pages[page])
                await message.remove_reaction(r, ctx.author)

            except asyncio.TimeoutError:
                await message.clear_reactions()
                break

    active_scrapes -= 1


# =========================
# COMMANDS
# =========================

@bot.command()
async def scrape(ctx, *, album: str):
    await scrape_queue.put((ctx, album))
    await ctx.send(f"In queue – positie {scrape_queue.qsize()} (gebruik format **Artist - Album**)")

@bot.command()
async def credits(ctx):
    await ctx.send(f"Je hebt **{user_credits.get(ctx.author.id, 0)}** credits over.")


# =========================
# RUN BOT
# =========================

bot.run(os.getenv("DISCORD_TOKEN"))
