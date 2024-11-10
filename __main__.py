import asyncio
import base64
import json
import time
import urllib.parse
import os
import sys

import aiohttp
import discord
from discord import ButtonStyle, Interaction, app_commands
from discord.ext import tasks
from discord.ui import Button, View
from loguru import logger

with open("config.json") as config_file:
    config = json.load(config_file)
    guild_id = config.get("guild_id")
    token = config.get("bot_token")
    if not guild_id or not token:
        raise ValueError("config.json is not valid. Please provide guild_id and bot_token.")

GUILD = discord.Object(id=guild_id)
TOKEN = token

class RadioBot:
    def __init__(self, bot):
        self.bot = bot
        self.stream_url = None
        self.track_name_url = None
        self.current_track = "Unknown Track"
        self.base_url = "https://play5.newradio.it/player/license/3992"
        self.playing = False
        self.track_info_updater = TrackInfoUpdater(self)
        self.last_message = None

    async def get_dynamic_url(self):
        timestamp = int(time.time() * 1000)
        params = {"_": timestamp}
        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params) as response:
                response.raise_for_status()
                data = await response.text()
                decoded_data = base64.b64decode(data).decode("utf-8")
                stream_data = json.loads(decoded_data)
                self.stream_url = stream_data["streams"][0][0]["url"]
                self.track_name_url = stream_data["streams"][0][0]["textUrl"]
                logger.info("Stream URL and track name URL updated successfully.")

    def create_player_embed(self, status="Now Playing", description=None, color=discord.Color.green()):
        """Helper method to create consistent embed messages"""
        embed = discord.Embed(
            title="🎵 Controlli Radio ATAC",
            color=color
        )
        embed.add_field(
            name=status,
            value=f"```{description or self.current_track}```",
            inline=False
        )
        embed.set_footer(text="❤️🧡 Radio ATAC • Musica della città ❤️🧡")
        return embed

    async def update_player_message(self, track_name):
        if self.last_message:
            try:
                embed = self.create_player_embed(description=track_name)
                await self.last_message.edit(embed=embed)
            except discord.NotFound:
                self.last_message = None

    async def play_stream(self, voice_client):
        """Helper method to start playing the stream"""
        await self.get_dynamic_url()
        if self.stream_url:
            ffmpeg_options = {
                "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                "options": "-vn -b:a 192k",
            }
            voice_client.stop()
            voice_client.play(
                discord.FFmpegPCMAudio(self.stream_url, **ffmpeg_options),
                after=lambda e: logger.error(f"Stream error: {e}") if e else None,
            )
            self.playing = True
            return True
        return False

    async def start_stream(self, interaction: Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message(
                "Please join a voice channel first.", ephemeral=True
            )
            logger.warning("Attempted to start stream without user in voice channel.")
            return False

        # Check if bot is already in a voice channel
        if interaction.guild.voice_client:
            # If bot is in the same channel as the user
            if interaction.guild.voice_client.channel == interaction.user.voice.channel:
                await interaction.response.send_message(
                    "I'm already playing in this channel!", ephemeral=True
                )
                logger.info("Attempted to join the same channel twice.")
                return False
            # If bot is in a different channel
            else:
                await interaction.response.send_message(
                    "I'm already in another voice channel! Please use /leave first.", ephemeral=True
                )
                logger.info("Attempted to join while bot was in another channel.")
                return False

        await interaction.response.defer()
        voice_channel = interaction.user.voice.channel
        voice_client = await voice_channel.connect()
        
        if await self.play_stream(voice_client):
            message = await interaction.followup.send(
                embed=self.create_player_embed(),
                view=RadioControlView(self)
            )
            self.last_message = message
            logger.info(f"Radio stream started in channel: {voice_channel.name}")
            return True
        else:
            await interaction.followup.send(
                content="Failed to retrieve stream URL.",
                view=RadioControlView(self)
            )
            logger.error("Stream URL is not set.")
            return False

    async def on_ready(self):
        self.track_info_updater.start_updater()
        logger.info("Track info updater started.")


class TrackInfoUpdater:
    def __init__(self, radio_bot):
        self.radio_bot = radio_bot
        self.update_track_name_task = None

    async def fetch_track_name(self):
        if not self.radio_bot.track_name_url:
            return "Unknown Track"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://play5.newradio.it{self.radio_bot.track_name_url}"
            ) as response:
                response.raise_for_status()
                data = await response.text()
                parsed_data = urllib.parse.parse_qs(data)
                track_name = parsed_data.get("title", ["Unknown Track"])[0]
                return track_name

    @tasks.loop(seconds=5)
    async def update_track_name(self):
        try:
            track_name = await self.fetch_track_name()
            if track_name != self.radio_bot.current_track:
                self.radio_bot.current_track = track_name
                # Update rich presence
                if self.radio_bot.playing:
                    activity = discord.Activity(
                        type=discord.ActivityType.listening,
                        name=track_name
                    )
                    await self.radio_bot.bot.change_presence(activity=activity)
                # Update player message
                await self.radio_bot.update_player_message(track_name)
                logger.info(f"Updated track name to: {track_name}")
        except Exception as e:
            logger.error(f"Error updating track name: {e}")

    def start_updater(self):
        self.update_track_name.start()

class RadioControlView(View):
    def __init__(self, radio_bot):
        super().__init__(timeout=None)
        self.radio_bot = radio_bot

    @discord.ui.button(label="", style=ButtonStyle.primary, emoji="⏸️")
    async def pause_button(self, interaction: Interaction, button: Button):
        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.pause()
            self.radio_bot.playing = False
            
            await interaction.response.edit_message(
                embed=self.radio_bot.create_player_embed(
                    status="Paused",
                    color=discord.Color.orange()
                ),
                view=self
            )
            logger.info("Radio paused.")

    @discord.ui.button(label="", style=ButtonStyle.success, emoji="⏯️")
    async def resume_button(self, interaction: Interaction, button: Button):
        vc = interaction.guild.voice_client
        if not vc:  # Bot is not in a voice channel
            if not interaction.user.voice:
                await interaction.response.send_message(
                    "Please join a voice channel first.", ephemeral=True
                )
                return
                
            # Connect and start playing
            vc = await interaction.user.voice.channel.connect()
            if await self.radio_bot.play_stream(vc):
                await interaction.response.edit_message(
                    embed=self.radio_bot.create_player_embed(
                        color=discord.Color.green()
                    ),
                    view=self
                )
                logger.info("Radio resumed with new connection.")
            else:
                await interaction.response.send_message(
                    "Failed to start the stream.", ephemeral=True
                )
        elif not vc.is_playing():  # Bot is in channel but not playing
            vc.resume()
            self.radio_bot.playing = True
            
            await interaction.response.edit_message(
                embed=self.radio_bot.create_player_embed(
                    color=discord.Color.green()
                ),
                view=self
            )
            logger.info("Radio resumed.")

    @discord.ui.button(label="", style=ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: Interaction, button: Button):
        if interaction.guild.voice_client:
            vc = interaction.guild.voice_client
            vc.stop()
            await vc.disconnect()
            self.radio_bot.playing = False
            
            await interaction.response.edit_message(
                embed=self.radio_bot.create_player_embed(
                    status="Stopped",
                    description="Disconnected from voice channel",
                    color=discord.Color.red()
                ),
                view=self
            )
            logger.info("Radio stopped and disconnected from voice channel.")


class MyBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.radio_bot = RadioBot(self)

    async def setup_hook(self):
        await self.tree.sync(guild=GUILD)
        logger.info("Commands registered and synced to guild.")

    async def on_ready(self):
        await self.radio_bot.on_ready()
        logger.info(f"Logged in as {self.user}")

intents = discord.Intents.default()
intents.message_content = True
client = MyBot(intents=intents)

@client.tree.command(name="join", description="Join the voice channel and start streaming")
async def join(interaction: discord.Interaction):
    await client.radio_bot.start_stream(interaction)
    logger.info(f"Join command executed for channel: {interaction.user.voice.channel.name if interaction.user.voice else 'None'}")

@client.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("Disconnected from the voice channel.", ephemeral=True)
        logger.info("Disconnected from the voice channel.")
    else:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)

@client.tree.command(name="radio", description="Control the radio playback")
async def radio_control(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎵 Controlli Radio ATAC",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="Status",
        value="Use the buttons below to control playback",
        inline=False
    )
    embed.set_footer(text="❤️🧡 Radio ATAC • Musica della città ❤️🧡")
    
    await interaction.response.send_message(
        embed=embed,
        view=RadioControlView(client.radio_bot),
        ephemeral=True
    )

if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        client.run(TOKEN)
    except KeyboardInterrupt:
        sys.exit()
