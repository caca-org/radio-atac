from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp
import discord
from discord import (ButtonStyle, Guild, Interaction, Message, VoiceChannel,
                     VoiceClient, app_commands)
from discord.ext import tasks
from discord.ui import Button, View
from discord.utils import MISSING
from dotenv import load_dotenv
from loguru import logger


class BotConfig:
    def __init__(self) -> None:
        load_dotenv()
        self.token = os.getenv("BOT_TOKEN")
        self.guild_id = os.getenv("GUILD_ID")

        if not self.guild_id or not self.token:
            raise ValueError(
                ".env is not valid. Please provide GUILD_ID and BOT_TOKEN."
            )

        try:
            self.guild_id = int(self.guild_id)
        except ValueError:
            raise ValueError("GUILD_ID must be a valid integer.")

        self.guild = discord.Object(id=self.guild_id)


@dataclass
class SongMetadata:
    query: str
    session: aiohttp.ClientSession

    BASE_URL: str = "https://itunes.apple.com/search"

    async def fetch(self) -> dict:
        try:
            async with self.session.get(
                self.BASE_URL,
                params={"term": self.query, "media": "music", "limit": "1"},
                headers={"Accept": "application/json"},
            ) as response:
                return await response.json(content_type=None)
        except Exception as e:
            logger.error(f"Error fetching iTunes data: {e}")
            return {"results": []}

    async def get_song(self) -> Optional[dict]:
        try:
            data = await self.fetch()
            return data["results"][0] if data.get("results") else None
        except Exception as e:
            logger.error(f"Error parsing song data: {e}")
            return

    @property
    async def artwork(self) -> str | False:
        song = await self.get_song()
        if not song:
            return False
        return song.get(
            "artworkUrl100", song.get("artworkUrl60", song.get("artworkUrl30", False))
        )


class RadioBot:
    def __init__(self, bot: Client) -> None:
        self.base_url: str = "https://play5.newradio.it/player/license/3992"
        self.bot: Client = bot
        self.stream_url: Optional[str] = None
        self.track_name_url: Optional[str] = None
        self.current_track: str = "Unknown Track"

        self.session: Optional[aiohttp.ClientSession] = None
        self.track_info_updater: Optional[TrackInfoUpdater] = None
        self.active_views: set[RadioControlView] = set()

        self.file = discord.File("assets/thumbnail.png", filename="thumbnail.png")
        self.placeholder = True

    async def setup(self) -> None:
        self.session = aiohttp.ClientSession()
        self.track_info_updater = TrackInfoUpdater(self)

        try:
            await self.get_dynamic_url()
            initial_track = await self.track_info_updater.fetch_track_name()
            self.current_track = initial_track
            await self.update_presence()
        except Exception as e:
            logger.error(f"Failed to fetch initial track info: {e}")

        self.track_info_updater.start_updater()
        logger.info("RadioBot setup completed")

    async def cleanup(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("RadioBot cleanup completed")

    async def get_dynamic_url(self) -> None:
        timestamp = int(time.time() * 1000)
        params: dict[str, Any] = {"_": timestamp}
        async with self.session.get(self.base_url, params=params) as response:
            response.raise_for_status()
            data = await response.text()
            decoded_data = base64.b64decode(data).decode("utf-8")
            stream_data = json.loads(decoded_data)
            self.stream_url = stream_data["streams"][0][0]["url"]
            self.track_name_url = stream_data["streams"][0][0]["textUrl"]
            logger.info("Stream URL and track name URL updated successfully.")

    async def create_player_embed(
        self,
        status: str = "Now Playing",
        description: Optional[str] = None,
        color: discord.Color = discord.Color.green(),
    ) -> discord.Embed:
        metadata = SongMetadata(self.current_track or description, self.session)
        artwork = await metadata.artwork
        if not artwork:
            logger.warning(
                f"No metadata found for {self.current_track or description}."
            )
        self.placeholder = not artwork

        embed = discord.Embed(title="🎵 Radio ATAC Controls", color=color)
        embed.add_field(
            name=status,
            value=f"```{description or self.current_track}```",
            inline=False,
        )
        embed.set_footer(text="❤️🧡 Radio ATAC • Musica della città ❤️🧡")
        embed.set_thumbnail(url=artwork or f"attachment://{self.file.filename}")
        return embed

    async def update_all_player_messages(
        self,
        track_name: str,
        status: str = "Now Playing",
        color: discord.Color = discord.Color.green(),
    ) -> None:
        update_tasks = []

        for view in list(self.active_views):
            try:
                if view.message:
                    embed = await self.create_player_embed(
                        status=status, description=track_name, color=color
                    )
                    update_tasks.append(
                        view.message.edit(
                            embed=embed,
                            attachments=[self.file] if self.placeholder else MISSING,
                        )
                    )
            except (discord.NotFound, AttributeError):
                self.active_views.discard(view)
                continue

        if update_tasks:
            await asyncio.gather(*update_tasks, return_exceptions=True)

    async def update_presence(self, track_name: Optional[str] = None) -> None:
        if not self.bot.is_ready():
            return

        track_name = track_name or self.current_track

        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name=f"{track_name}",
            state="📻 Radio ATAC",
            details="🎶 Musica della città",
        )

        await self.bot.change_presence(activity=activity)

    async def play_stream(self, voice_client: VoiceClient) -> bool:
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
            await self.update_presence()
            return True
        return False

    async def start_stream(self, interaction: Interaction) -> bool:
        if not isinstance(interaction.guild, Guild):
            await interaction.response.send_message(
                "This command can only be used in a guild.", ephemeral=True
            )
            return False

        if not interaction.user.voice:
            await interaction.response.send_message(
                "Please join a voice channel first.", ephemeral=True
            )
            logger.warning("Attempted to start stream without user in voice channel.")
            return False

        if interaction.guild.voice_client:
            if interaction.guild.voice_client.channel == interaction.user.voice.channel:
                view = RadioControlView(self)
                embed = await self.create_player_embed()
                await interaction.response.send_message(
                    embed=embed,
                    file=self.file if self.placeholder else MISSING,
                    view=view,
                    ephemeral=True,
                )
                view.message = await interaction.original_response()
                self.active_views.add(view)
                logger.info("Sent radio controls for existing stream.")
                return True
            else:
                await interaction.response.send_message(
                    "I'm already in another voice channel! Please use /leave first.",
                    ephemeral=True,
                )
                logger.info("Attempted to join while bot was in another channel.")
                return False

        await interaction.response.defer()
        voice_channel = interaction.user.voice.channel
        if not isinstance(voice_channel, VoiceChannel):
            await interaction.followup.send(
                "Cannot join this type of voice channel.", ephemeral=True
            )
            return False

        voice_client = await voice_channel.connect()
        if await self.play_stream(voice_client):
            view = RadioControlView(self)
            embed = await self.create_player_embed()
            message = await interaction.followup.send(
                embed=embed,
                file=self.file if self.placeholder else MISSING,
                view=view,
                ephemeral=True,
            )
            view.message = message
            self.active_views.add(view)
            logger.info(f"Radio stream started in channel: {voice_channel.name}")
            return True
        else:
            await interaction.followup.send(
                content="Failed to retrieve stream URL.", ephemeral=True
            )
            logger.error("Stream URL is not set.")
            return False


class TrackInfoUpdater:
    def __init__(self, radio_bot: RadioBot) -> None:
        self.radio_bot = radio_bot

    async def fetch_track_name(self) -> str:
        if not self.radio_bot.track_name_url:
            return "Unknown Track"
        async with self.radio_bot.session.get(
            f"https://play5.newradio.it{self.radio_bot.track_name_url}"
        ) as response:
            response.raise_for_status()
            data = await response.text()
            parsed_data = urllib.parse.parse_qs(data)
            track_name = parsed_data.get("title", ["Unknown Track"])[0]
            return track_name

    @tasks.loop(seconds=5)
    async def update_track_name(self) -> None:
        try:
            track_name = await self.fetch_track_name()
            if track_name != self.radio_bot.current_track:
                self.radio_bot.current_track = track_name

                await asyncio.gather(
                    self.radio_bot.update_presence(track_name),
                    self.radio_bot.update_all_player_messages(track_name),
                    return_exceptions=True,
                )
                logger.info(f"Updated track name to: {track_name}")
        except Exception as e:
            logger.error(f"Error updating track name: {e}")

    def start_updater(self) -> None:
        self.update_track_name.start()


class RadioControlView(View):
    def __init__(self, radio_bot: RadioBot) -> None:
        super().__init__(timeout=None)
        self.radio_bot = radio_bot
        self.message: Optional[Message] = None

    @discord.ui.button(label="", style=ButtonStyle.primary, emoji="⏸️")
    async def pause_button(self, interaction: Interaction, button: Button) -> None:
        if not isinstance(interaction.guild, Guild):
            return

        if (
            interaction.guild.voice_client
            and interaction.guild.voice_client.is_playing()
        ):
            interaction.guild.voice_client.pause()

            await self.radio_bot.update_all_player_messages(
                self.radio_bot.current_track,
                status="Paused",
                color=discord.Color.orange(),
            )
            await interaction.response.defer()
            logger.info("Radio paused.")

    @discord.ui.button(label="", style=ButtonStyle.success, emoji="⏯️")
    async def resume_button(self, interaction: Interaction, button: Button) -> None:
        if not isinstance(interaction.guild, Guild):
            return

        vc = interaction.guild.voice_client
        if not vc:
            if not interaction.user.voice:
                await interaction.response.send_message(
                    "Please join a voice channel first.", ephemeral=True
                )
                return

            if not isinstance(interaction.user.voice.channel, VoiceChannel):
                await interaction.response.send_message(
                    "Cannot join this type of voice channel.", ephemeral=True
                )
                return
            await interaction.response.defer()

            vc = await interaction.user.voice.channel.connect()
            if await self.radio_bot.play_stream(vc):
                await self.radio_bot.update_all_player_messages(
                    self.radio_bot.current_track, color=discord.Color.green()
                )
                logger.info("Radio resumed with new connection.")
                return

        elif vc.is_paused():
            vc.resume()
            await self.radio_bot.update_all_player_messages(
                self.radio_bot.current_track,
                status="Now Playing",
                color=discord.Color.green(),
            )
            await self.radio_bot.update_presence()
            await interaction.response.defer()
            logger.info("Radio resumed.")
        else:
            await interaction.response.defer()
            logger.info("Radio already playing.")

    @discord.ui.button(label="", style=ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: Interaction, button: Button) -> None:
        if not isinstance(interaction.guild, Guild):
            return

        if interaction.guild.voice_client:
            vc = interaction.guild.voice_client
            vc.stop()
            await vc.disconnect()

            # Update all player messages to indicate stopped state
            await self.radio_bot.update_all_player_messages(
                "Disconnected from voice channel",
                status="Stopped",
                color=discord.Color.red(),
            )
            await interaction.response.defer()
            logger.info("Radio stopped and disconnected from voice channel.")


class Client(discord.Client):
    def __init__(self, *, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.radio_bot = RadioBot(self)
        self.config = BotConfig()

    async def setup_hook(self) -> None:
        await self.tree.sync(guild=self.config.guild)
        await self.radio_bot.setup()
        logger.info("Commands registered and synced to guild.")

    async def close(self) -> None:
        await self.radio_bot.cleanup()
        await super().close()

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user}")


def setup_bot() -> Client:
    intents = discord.Intents.default()
    intents.message_content = True
    return Client(intents=intents)


client = setup_bot()


@client.tree.command(
    name="join", description="Join the voice channel and start streaming"
)
async def join(interaction: discord.Interaction):
    await client.radio_bot.start_stream(interaction)
    logger.info(
        f"Join command executed for channel: {interaction.user.voice.channel.name if interaction.user.voice else 'None'}"
    )


@client.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: Interaction) -> None:
    if not isinstance(interaction.guild, Guild):
        await interaction.response.send_message(
            "This command can only be used in a guild.", ephemeral=True
        )
        return

    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message(
            "Disconnected from the voice channel.", ephemeral=True
        )
        logger.info("Disconnected from the voice channel.")
    else:
        await interaction.response.send_message(
            "I'm not in a voice channel.", ephemeral=True
        )


@client.tree.command(
    name="radio", description="Show radio controls and join voice channel"
)
async def radio_control(interaction: Interaction) -> None:
    await client.radio_bot.start_stream(interaction)
    logger.info("Radio command executed")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        client.run(client.config.token)
    except KeyboardInterrupt:
        sys.exit()
