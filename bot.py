import os
import threading
from flask import Flask
import discord
from discord.ext import commands
import asyncio
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import re
import urllib.parse

# -------------------------
# FLASK KEEP-ALIVE (Render)
# -------------------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# start flask in a thread
threading.Thread(target=run_flask, daemon=True).start()

# -------------------------
# DISCORD BOT SETUP
# -------------------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

scraper = cloudscraper.create_scraper()

def slug(t):
    return t.strip().replace(" ", "-")

def build_album_links(text):
    links = []
    if " - " in text:
        artist, album = text.split(" - ", 1)
        a = slug(artist)
        b = slug(album)
        links.append(f"https://genius.com/albums/{a}/{b}")
        links.append(f"https://genius.com/albums/{a.title()}/{b.title()}")
    return links

def search_genius(query):
    q = urllib.parse.quote_plus(query)
    url = f"https://genius.com/search?q={q}"
    try:
        r = scraper.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            if "/albums/" in a["href"]:
                href = a["href"]
                if href.startswith("/"):
                    href = "https://genius.com" + href
                return href
    except:
        pass
    return None

def parse_producers(html):
    soup = BeautifulSoup(html, "html.parser")
    producers = []

    for unit in soup.select("div.metadata_unit"):
        lbl = unit.get_text(" ", strip=True).lower()
        if "producer" in lbl:
            for a in unit.select("a"):
                name = a.get_text(strip=True)
                ig = re.sub(r"[^a-z0-9]", "", name.lower())
                producers.append(f"**{name}** → @{ig}")

    return producers

# -------------------------
# DISCORD COMMAND
# -------------------------

@bot.command()
async def scrape(ctx, *, text):
    await ctx.send("Scraping…")

    print("DEBUG: command received:", text)

    # 1) Try direct URLs
    for url in build_album_links(text):
        print("DEBUG trying:", url)
        try:
            r = scraper.get(url)
            if r.status_code == 200 and len(r.text) > 2000:
                prods = parse_producers(r.text)
                if prods:
                    await ctx.send("\n".join(prods))
                    return
        except:
            pass

    # 2) Search fallback
    print("DEBUG direct failed, searching…")
    found = search_genius(text)
    print("DEBUG search result:", found)

    if not found:
        await ctx.send("Album niet gevonden via Genius search.")
        return

    r = scraper.get(found)
    prods = parse_producers(r.text)

    if not prods:
        await ctx.send("Geen producers gevonden.")
    else:
        await ctx.send("\n".join(prods))

# -------------------------
# START BOT
# -------------------------

TOKEN = os.getenv("DISCORD_TOKEN")

print("DEBUG: starting Discord bot…")
bot.run(TOKEN)
