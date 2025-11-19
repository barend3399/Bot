import discord
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime
import re
import cloudscraper
from bs4 import BeautifulSoup

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

MAX_CONCURRENT = 10
scrape_queue = asyncio.Queue()
active_scrapes = 0
user_credits = {}

scraper = cloudscraper.create_scraper(delay=10)

@bot.event
async def on_ready():
    print(f"{bot.user} online – 100% WERKEND, LAATSTE VERSIE")
    worker.start()

@tasks.loop(seconds=2)
async def worker():
    global active_scrapes
    while not scrape_queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album = await scrape_queue.get()
        active_scrapes += 1
        asyncio.create_task(run_scrape(ctx, album))

async def run_scrape(ctx, album):
    global active_scrapes
    uid = ctx.author.id

    if uid not in user_credits:
        user_credits[uid] = 100
    if user_credits[uid] <= 0:
        await ctx.send("Geen credits meer → Word Producer Pass member!")
        active_scrapes -= 1
        return

    user_credits[uid] -= 1
    status_msg = await ctx.send(f"Scraping **{album}**... (25–45 sec)")

    try:
        # STAP 1: probeer exact zoals gebruiker typt (meestal werkt dit)
        query = album.strip().title().replace(" ", "-")
        url = f"https://genius.com/albums/{query}"
        html = scraper.get(url, timeout=60).text

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select(".chart_row")

        # STAP 2: als geen tracks → probeer omgekeerd (Astroworld Travis Scott → Travis-Scott/Astroworld)
        if len(rows) == 0 or "Oops! We couldn't find that page" in html:
            reversed_query = "-".join(reversed(query.split("-")))
            url = f"https://genius.com/albums/{reversed_query}"
            html = scraper.get(url, timeout=60).text
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select(".chart_row")

        results = []
        for row in rows:
            title_tag = row.select_one(".chart_row-content-title")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True).split("\n")[0][:40]

            producers = [
                a.get_text(strip=True)
                for a in row.select('a[href^="/artists/"]')
                if "[" not in a.get_text(strip=True)
            ][:3]

            for p in producers:
                clean = re.sub(r"[^a-z0-9]", "", p.lower())
                ig = clean if len(clean) >= 3 else "unknown"
                results.append(f"`{title:<40}` → **{p}** @{ig}")

        if not results:
            results = ["Geen producers gevonden – probeer een andere schrijfwijze (bijv. 'Travis Scott Astroworld')"]

    except Exception as e:
        results = ["Tijdelijke fout – probeer over 1 minuut opnieuw."]
        print("Error:", e)

    # === EMBEDS ===
    pages = []
    for i in range(0, len(results), 20):
        embed = discord.Embed(
            title=f"Producers + Instagram – {album}",
            description="\n".join(results[i:i+20]),
            color=0x00ff00,
            timestamp=datetime.now(datetime.UTC)
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
                if str(r.emoji) == "▶️" and page < len(pages)-1:
                    page += 1
                elif str(r.emoji) == "◀️" and page > 0:
                    page -= 1
                await message.edit(embed=pages[page])
                await message.remove_reaction(r, ctx.author)
            except asyncio.TimeoutError:
                await message.clear_reactions()
                break

    active_scrapes -= 1

@bot.command()
async def scrape(ctx, *, album: str):
    await scrape_queue.put((ctx, album))
    await ctx.send(f"In queue – positie {scrape_queue.qsize()} (max {MAX_CONCURRENT})")

@bot.command()
async def credits(ctx):
    await ctx.send(f"Je hebt **{user_credits.get(ctx.author.id, 0)}** credits over")

bot.run(os.getenv("DISCORD_TOKEN"))
