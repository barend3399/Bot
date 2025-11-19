import discord
from discord.ext import commands, tasks
import asyncio
import os
import re
from datetime import datetime, timezone
import cloudscraper
from bs4 import BeautifulSoup

# ======== BOT CONFIG ========
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

MAX_CONCURRENT = 10
scrape_queue = asyncio.Queue()
active_scrapes = 0
user_credits = {}

scraper = cloudscraper.create_scraper(delay=10)

# ======== EVENTS ========
@bot.event
async def on_ready():
    print(f"{bot.user} is online!")
    worker.start()

# ======== QUEUE WORKER ========
@tasks.loop(seconds=2)
async def worker():
    global active_scrapes
    while not scrape_queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album_input = await scrape_queue.get()
        active_scrapes += 1
        asyncio.create_task(run_scrape(ctx, album_input))

# ======== SCRAPER ========
async def run_scrape(ctx, album_input):
    global active_scrapes
    uid = ctx.author.id
    user_credits[uid] = user_credits.get(uid, 100)

    if user_credits[uid] <= 0:
        await ctx.send("Geen credits meer → Word Producer Pass member!")
        active_scrapes -= 1
        return

    user_credits[uid] -= 1
    status_msg = await ctx.send(f"Scraping **{album_input}**... (20–50 sec)")

    # Genius URL variants
    variants = [
        album_input.strip().title().replace(" ", "-"),
        "-".join(reversed(album_input.strip().title().split())),
        album_input.strip().lower().replace(" ", "-"),
        album_input.strip().replace(" ", "-").title(),
    ]

    html = ""
    urls_tried = []
    for query in variants:
        url = f"https://genius.com/albums/{query}"
        urls_tried.append(url)
        try:
            html = scraper.get(url, timeout=50).text
            if "Oops! We couldn't find that page" not in html and len(html) > 20000:
                break
        except:
            continue

    results = []
    if not html or "Oops" in html:
        results = [f"Album niet gevonden. Probeerde:\n" + "\n".join([f"• {u}" for u in urls_tried[:3]])]
    else:
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select(".chart_row")
        for row in rows:
            title_tag = row.select_one(".chart_row-content-title")
            if not title_tag:
                continue
            track = title_tag.get_text(strip=True).split("\n")[0][:40]
            producers = [
                a.get_text(strip=True)
                for a in row.select('a[href^="/artists/"]')
                if "[" not in a.get_text(strip=True) and "]" not in a.get_text(strip=True)
            ][:3]
            for p in producers:
                clean = re.sub(r"[^a-z0-9]", "", p.lower())
                ig = clean if len(clean) >= 3 else "-"
                results.append(f"`{track:<40}` → **{p}** @{ig}")

        if not results:
            results = ["Geen producers gevonden op deze pagina (mogelijk privé album)"]

    # EMBED PAGINATION
    pages = []
    for i in range(0, len(results), 20):
        embed = discord.Embed(
            title=f"Producers + Instagram – {album_input}",
            description="\n".join(results[i:i+20]),
            color=0x00ff00,
            timestamp=datetime.now(timezone.utc)
        )
        total = (len(results)-1)//20 + 1
        embed.set_footer(text=f"Pagina {i//20 + 1}/{total} • Credits: {user_credits[uid]}")
        pages.append(embed)

    await status_msg.edit(content=f"**Klaar!** {len(results)} Instagram-handles gevonden")
    message = await ctx.send(embed=pages[0])

    if len(pages) > 1:
        await message.add_reaction("◀️")
        await message.add_reaction("▶️")
        page = 0
        def check(r, u):
            return u == ctx.author and r.message.id == message.id and str(r.emoji) in ["◀️", "▶️"]
        while True:
            try:
                r, _ = await bot.wait_for("reaction_add", timeout=120, check=check)
                if str(r.emoji) == "▶️" and page < len(pages)-1: page += 1
                elif str(r.emoji) == "◀️" and page > 0: page -= 1
                await message.edit(embed=pages[page])
                await message.remove_reaction(r, ctx.author)
            except asyncio.TimeoutError:
                await message.clear_reactions()
                break

    active_scrapes -= 1

# ======== COMMANDS ========
@bot.command()
async def scrape(ctx, *, album_input: str):
    if scrape_queue.qsize() == 0:
        await scrape_queue.put((ctx, album_input))
        await ctx.send(f"Scraping gestart – positie 1")
    else:
        await scrape_queue.put((ctx, album_input))
        await ctx.send(f"In queue – positie {scrape_queue.qsize()}")

@bot.command()
async def credits(ctx):
    await ctx.send(f"Je hebt **{user_credits.get(ctx.author.id, 0)}** credits over")

# ======== RUN BOT ========
bot.run(os.getenv("DISCORD_TOKEN"))
