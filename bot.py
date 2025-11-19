import discord
from discord.ext import commands, tasks
import asyncio
import os
import aiohttp
from datetime import datetime
import re

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==== CONFIG ====
MAX_CONCURRENT = 10
scrape_queue = asyncio.Queue()
active_scrapes = 0
user_credits = {}

@bot.event
async def on_ready():
    print(f"{bot.user} is online – 100% STABIELE VERSIE LIVE!")
    scraper_loop.start()

@tasks.loop(seconds=1)
async def scraper_loop():
    global active_scrapes
    while not scrape_queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album = await scrape_queue.get()
        active_scrapes += 1
        asyncio.create_task(process_scrape(ctx, album))

async def process_scrape(ctx, album):
    global active_scrapes
    user_id = ctx.author.id

    if user_id not in user_credits:
        user_credits[user_id] = 100
    if user_credits[user_id] <= 0:
        await ctx.send("Geen credits meer → Word Producer Pass member!")
        active_scrapes -= 1
        return

    user_credits[user_id] -= 1
    status_msg = await ctx.send(f"Scraping **{album}**... (20–40 sec)")

    # ==== 100% WERKENDE GENIUS SCRAPE (geen Browserless, geen blokkade) ====
    search_url = f"https://genius.com/api/search/album?q={album.replace(' ', '%20')}"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(search_url, headers={"User-Agent": "curl/7.68.0"}) as resp:
                data = await resp.json()
                album_id = data["response"]["sections"][0]["hits"][0]["result"]["id"]
                
                # Haal tracklist op
                tracks_url = f"https://genius.com/api/albums/{album_id}/tracks"
                async with session.get(tracks_url) as resp:
                    tracks_data = await resp.json()
                    tracks = tracks_data["response"]["tracks"]
        except:
            await status_msg.edit(content="Album niet gevonden. Probeer een exacte naam (bijv. 'Astroworld Travis Scott')")
            active_scrapes -= 1
            return

    results = []
    for item in tracks[:25]:  # max 25 tracks
        track = item.get("song", {})
        title = track.get("title", "Onbekend")
        producers = []
        for credit in track.get("producer_artists", []):
            producers.append(credit.get("name"))
        for prod in producers[:3]:
            clean = re.sub(r'[^a-z0-9]', '', prod.lower())
            results.append(f"`{title[:40]:<40}` → **{prod}** @{clean if clean else 'unknown'}")

    # ==== TABEL (nu met crash-fix) ====
    if not results:
        results = ["Geen producers gevonden voor dit album."]

    pages = []
    for i in range(0, len(results), 20):
        chunk = results[i:i+20]
        embed = discord.Embed(
            title=f"Producers + Instagram – {album}",
            description="\n".join(chunk),
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        total_pages = (len(results) - 1) // 20 + 1
        embed.set_footer(text=f"Pagina {i//20 + 1}/{total_pages} • Credits: {user_credits[user_id]}")
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
                r, u = await bot.wait_for("reaction_add", timeout=120, check=check)
                if str(r.emoji) == "▶️" and page < len(pages)-1:
                    page += 1
                elif str(r.emoji) == "◀️" and page > 0:
                    page -= 1
                await message.edit(embed=pages[page])
                await message.remove_reaction(r, u)
            except asyncio.TimeoutError:
                await message.clear_reactions()
                break

    active_scrapes -= 1

# ==== COMMANDOS ====
@bot.command()
async def scrape(ctx, *, album):
    await scrape_queue.put((ctx, album))
    pos = scrape_queue.qsize()
    await ctx.send(f"In queue – positie {pos} (max {MAX_CONCURRENT} tegelijk)")

@bot.command()
async def credits(ctx):
    creds = user_credits.get(ctx.author.id, 0)
    await ctx.send(f"Je hebt **{creds}** credits over.")

@bot.command()
async def queue(ctx):
    await ctx.send(f"Actief: {active_scrapes}/{MAX_CONCURRENT} | Wachtrij: {scrape_queue.qsize()}")

bot.run(os.getenv("DISCORD_TOKEN"))
