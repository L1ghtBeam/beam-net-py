# beam-net
Matchmaking service for Splatoon 2 using Discord.

## Setting Up:

Use python 3.9. Set up a venv or other virtual environment. Install dependencies with
``pip install -r requirements.txt``.

Add a `bot.json` file to your project. Use `bot_sample.txt` for a guide.

Program uses postgres for the database. File `postgres-db-setup.sql` should set up the database schema.

Program requires a central discord server with two roles for "admin" and "registered," and a channel named `#modes`.