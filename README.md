# 🚇 Radio ATAC Discord Bot 🎵

## What is this?

A Discord bot that brings the official radio station of [Roma Mobilità](https://romamobilita.it/) directly to your Discord server. Experience the authentic sounds of Rome's public transport system while chatting with your friends!

## Why?

Because waiting for the 64 bus gives you plenty of time to appreciate good music 🚌

## Prerequisites

- Python 3.8 or higher
- FFmpeg
- A Discord Bot Token
- A Discord Server (Guild)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/caca-org/radio-atac
cd radio-atac
```

2. Create and activate a virtual environment:
```bash
# Create virtual environment
python -m venv .venv

# Activate it on Unix/macOS
source .venv/bin/activate

# Or on Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Or on Windows (Command Prompt)
.\.venv\Scripts\activate.bat
```

3. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

1. Create a `.env` file in the project root:
```bash
cp .env.example .env
```

2. Edit the `.env` file with your Discord bot token and server ID:
```env
BOT_TOKEN=your_discord_bot_token_here
GUILD_ID=your_guild_id_here
```

To get these values:
- **Bot Token**: Create a bot application on the [Discord Developer Portal](https://discord.com/developers/applications)
- **Guild ID**: Enable Developer Mode in Discord settings, then right-click your server and select "Copy ID"

## Running the Bot

1. Make sure your virtual environment is activated
2. Start the bot:
```bash
python __main__.py
```

## Usage

The bot responds to the following slash commands:
- `/radio` - Shows the radio controls and joins your voice channel
- `/join` - Makes the bot join your voice channel
- `/leave` - Disconnects the bot from voice channel

## Acknowledgments

- Thanks to [Roma Mobilità](https://romamobilita.it/) for providing the radio stream
- All the patient commuters waiting for the Metro C to resume service

### 🚌 Enjoy the soothing sounds of Rome's public transport! 🎵

*Note: This is an unofficial project and is not affiliated with ATAC or Roma Mobilità.*