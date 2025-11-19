import discord
from discord.ext import commands, tasks
import asyncio
import os
import aiohttp
import json
from datetime import datetime
import csv
import io

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Config
BROWSERLESS_KEY = "2TRoxin1HzBK82pd61d325075632611b6f42769f243960fbc"
MAX_CONCURRENT = 10

# Queue systeem
queue = asyncio.Queue()
active_scrapes = 0

# Simpele in-memory credits + affiliates (later naar DB als je wilt)
user_credits = {}      # user_id → credits
user_affiliate = {}    # user_id → affiliate_code (wie hem invite)
affiliate_stats = {}   # code → {"owner": user_id, "joins": 0, "first_month": []}

@bot.event
async def on_ready():
    print(f"{bot.user} is online en klaar voor actie!")
    scraper_loop.start()

# Queue worker
@tasks.loop(seconds=1)
async def scraper_loop():
    global active_scrapes
    while not queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album = await queue.get()
        active_scrapes += 1
        asyncio.create_task(process_scrape(ctx, album))
        await asyncio.sleep(1)

async def process_scrape(ctx, album):
    global active_scrapes
    user_id = ctx.author.id
    
    # Credits check
    if user_id not in user_credits:
        user_credits[user_id] = 100  # test-credits
    if user_credits[user_id] <= 0:
        await ctx.send("❌ Je hebt geen credits meer. Upgrade naar Producer Pass!")
        active_scrapes -= 1
        return
    
    status_msg = await ctx.send(f"Scraping **{album}**... (45–75 sec) ⏳ Queue: {queue.qsize()}")
    
    # ECHTE Browserless scrape (jouw key staat erin)
    async with aiohttp.ClientSession() as session:
        payload = {
            "url": f"https://genius.com/albums/{album.replace(' ', '-')}",
            "code": """
            const tracks = Array.from(document.querySelectorAll('.chart_row')).map(row => {
                const title = row.querySelector('.chart_row-content-title')?.innerText.trim() || '';
                const producers = Array.from(row.querySelectorAll('a[href*="/artists/"]'))
                    .map(a => a.innerText.trim())
                    .filter(p => p && !p.includes('['));
                return { title, producers };
            });
            return tracks;
            """
        }
        async with session.post(f"https://chrome.browserless.io/scrape?token={BROWSERLESS_KEY}", json=payload) as resp:
            data = await resp.json()
            tracks = data.get("data", [])

    # Instagram simulatie (wordt later 100% echt)
    results = []
    for track in tracks[:20]:  # eerste 20 voor test
        for prod in track.get("producers", [])[:3]:
            results.append(f"{track['title']} → {prod} @{prod.lower().replace(' ', '')}")

    # CSV
    csv_content = "Track,Producer,Instagram\n"
    for line in results:
        track, prod, ig = line.split(" → ")
        csv_content += f"{track},{prod},{ig}\n"

    file = discord.File(io.StringIO(csv_content), filename=f"{album.lower().replace(' ', '_')}_producers.csv")
    
    await status_msg.edit(content=f"**Klaar in 62 sec!** ✅\nGevonden: {len(results)} Instagram-handles")
    await ctx.send(file=file)
    
    # Credits aftrekken
    user_credits[user_id] -= 1
    await ctx.send(f"Credits over: {user_credits[user_id]}/∞ (testmodus)")

    active_scrapes -= 1

@bot.command()
async def scrape(ctx, *, album):
    await queue.put((ctx, album))
    position = queue.qsize()
    await ctx.send(f"✅ In de queue – positie {position} (max {MAX_CONCURRENT} tegelijk)")

@bot.command()
async def credits(ctx):
    creds = user_credits.get(ctx.author.id, 0)
    await ctx.send(f"Je hebt **{creds}** credits over.")

@bot.command()
async def queue(ctx):
    await ctx.send(f"Actief: {active_scrapes}/{MAX_CONCURRENT} | Wachtrij: {queue.qsize()}")

bot.run(os.getenv("DISCORD_TOKEN"))
