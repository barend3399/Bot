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
queue = asyncio.Queue()
active = 0
credits = {}

scraper = cloudscraper.create_scraper(delay=10)

@bot.event
async def on_ready():
    print(f"{bot.user} online – FINAL CLOUDSRAPER")
    worker.start()

@tasks.loop(seconds=2)
async def worker():
    global active
    while not queue.empty() and active < MAX_CONCURRENT:
        ctx, album = await queue.get()
        active += 1
        asyncio.create_task(run_scrape(ctx, album))

async def run_scrape(ctx, album):
    global active
    uid = ctx.author.id
    credits[uid] = credits.get(uid, 100)

    if credits[uid] <= 0:
        await ctx.send("Geen credits meer → Word Producer Pass member!")
        active -= 1
        return

    credits[uid] -= 1
    msg = await ctx.send(f"Scraping **{album}**... (25–45 sec)")

    try:
        # CORRECTE URL (geen komma meer!)
        clean_album = album.strip().title().replace(" ", "-")
        url = f"https://genius.com/albums/{clean_album}"
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
            results = ["Geen producers gevonden – probeer exacte naam (bijv. 'Astroworld Travis Scott')"]

    except Exception as e:
        results = [f"Tijdelijke fout – probeer over 1 minuut opnieuw."]

    # === EMBEDS ===
    pages = []
    for i in range(0, len(results), 20):
        embed = discord.Embed(
            title=f"Producers + Instagram – {album}",
            description="\n".join(results[i:i+20]),
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        total = (len(results)-1)//20 + 1
        embed.set_footer(text=f"Pagina {i//20 + 1}/{total} • Credits: {credits[uid]}")
        pages.append(embed)

    await msg.edit(content=f"**Klaar!** {len(results)} handles gevonden")
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

    active -= 1

@bot.command()
async def scrape(ctx, *, album: str):
    await queue.put((ctx, album))
    await ctx.send(f"In queue – positie {queue.qsize()} (max {MAX_CONCURRENT})")

@bot.command()
async def credits(ctx):
    await ctx.send(f"Je hebt **{credits.get(ctx.author.id, 0)}** credits over")

bot.run(os.getenv("DISCORD_TOKEN"))
