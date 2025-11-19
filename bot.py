import discord
from discord.ext import commands, tasks
import asyncio
import os
import aiohttp
from datetime import datetime
from bs4 import BeautifulSoup
import re

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==== CONFIG ====
BROWSERLESS_KEY = "2TRoxin1HzBK82pd61d325075632611b6f42769f243960fbc"
MAX_CONCURRENT = 10

# Queue & data
scrape_queue = asyncio.Queue()
active_scrapes = 0
user_credits = {}

@bot.event
async def on_ready():
    print(f"{bot.user} is online – GENIUS FALLBACK LIVE!")
    scraper_loop.start()

# ==== QUEUE WORKER ====
@tasks.loop(seconds=1)
async def scraper_loop():
    global active_scrapes
    while not scrape_queue.empty() and active_scrapes < MAX_CONCURRENT:
        ctx, album = await scrape_queue.get()
        active_scrapes += 1
        asyncio.create_task(process_scrape(ctx, album))

# ==== HOOFD SCRAPE FUNCTIE ====
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
    status_msg = await ctx.send(f"Scraping **{album}**... (45–90 sec) | Wachtrij: {scrape_queue.qsize()}")

    tracks = []
    success = False

    # ==== POGING 1: Browserless (stealth) ====
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "url": f"https://genius.com/albums/{album.replace(' ', '-')}",
                "code": """
                await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
                await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
                await page.waitForSelector('.chart_row', { timeout: 30000 });
                return await page.content();
                """
            }
            async with session.post(
                f"https://chrome.browserless.io/content?token={BROWSERLESS_KEY}",
                json=payload,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=90
            ) as resp:
                html = await resp.text()

                if "challenge" not in html.lower() and len(html) > 50000:
                    soup = BeautifulSoup(html, 'html.parser')
                    for row in soup.select('.chart_row'):
                        title_el = row.select_one('.chart_row-content-title')
                        title = title_el.get_text(strip=True).split('\n')[0] if title_el else "Onbekend"
                        producers = [a.get_text(strip=True) for a in row.select('a[href*="/artists/"]') if '[' not in a.get_text() and ']' not in a.get_text()]
                        if title and producers:
                            tracks.append({"title": title, "producers": producers})
                    success = True
    except:
        pass

    # ==== FALLBACK: Simpele requests (als Browserless faalt) ====
    if not success:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://genius.com/albums/{album.replace(' ', '-')}",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                    timeout=30
                ) as resp:
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    for row in soup.select('.chart_row'):
                        title_el = row.select_one('.chart_row-content-title')
                        title = title_el.get_text(strip=True).split('\n')[0] if title_el else "Onbekend"
                        producers = [a.get_text(strip=True) for a in row.select('a[href*="/artists/"]') if '[' not in a.get_text() and ']' not in a.get_text()]
                        if title and producers:
                            tracks.append({"title": title, "producers": producers})
                    success = True
        except:
            await status_msg.edit(content="Tijdelijke blokkade. Probeer over 5–10 min opnieuw.")
            active_scrapes -= 1
            return

    if not success:
        active_scrapes -= 1
        return

    # ==== DISCORD TABEL ====
    results = []
    for track in tracks:
        title = track.get("title", "Onbekend")[:40]
        for prod in track.get("producers", [])[:3]:
            clean = re.sub(r'[^a-z0-9]', '', prod.lower())
            results.append(f"`{title:<40}` → **{prod}** @{clean}")

    pages = []
    for i in range(0, len(results), 20):
        chunk = results[i:i+20]
        page_text = "\n".join(chunk) if chunk else "Geen producers gevonden."
        embed = discord.Embed(
            title=f"Producers + Instagram – {album}",
            description=page_text,
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
