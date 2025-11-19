import discord
from discord.ext import commands
import asyncio
import io
import os

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user} is nu online in {len(bot.guilds)} server(s)!")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong! Bot werkt ")

@bot.command()
async def scrape(ctx, *, album="Astroworld Travis Scott"):
    msg = await ctx.send("Scraping gestart... dit duurt 45–75 seconden ⏳")
    await asyncio.sleep(8)  # test-delay
    result = ("**Klaar!** (testversie)\n"
              "Album: Astroworld – Travis Scott\n"
              "Producers gevonden: 78\n"
              "Instagram handles: 71 van de 78\n\n"
              "Zodra je zegt “GO LIVE” zet ik de echte Browserless + 60-seconde versie erin")
    csv = "Track,Producer,Instagram\nSTARGAZING,Mike Dean,@therealmikedean\nCAROUSEL,Hit-Boy,@hitboy"
    file = discord.File(io.StringIO(csv), filename="test_producers.csv")
    await msg.edit(content=result)
    await ctx.send(file=file)

bot.run(os.getenv("DISCORD_TOKEN"))
