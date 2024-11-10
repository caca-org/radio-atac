# Radio ATAC Discord bot

## What is this?

This bot streams music directly from the official radio of [Romamobilità](https://romamobilita.it/it) in your Discord server.

## Why?

Because God gave us free will 

## Installation

1. Clone the repository:
    ```bash
    git clone https://github.com/caca-org/RadioATAC.git
    cd RadioATAC
    ```

2. Create and activate a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
    ```

3. Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1. Rename the `config.json.example` to `config.json`
    ```bash
    mv config.json.example config.json
    ```
2. Add your Discord bot token and Guild ID to the file:
    ```json
    {
        "bot_token": "your_discord_bot_token",
        "guild_id": 1234567890
    }
    ```

## Running the Bot

1. Start the bot:
    ```bash
    python __main__.py
    ```

### Enjoy the soothing music of Radio ATAC
