# little-beepo
beta test tracker bot for pvkii discord server

# how
assuming debian gnu/linux and python3 is installed:

1. `mkdir ~/.venvs`

2. `python3 -m venv ~/.venvs/discord` (called 'discord' here, can be whatever)

3. `source ~/.venvs/discord/bin/activate`

4. `pip install discord.py`

5. `pip freeze > requirements.txt` (optional)

6. `export DISCORD_TOKEN=YOUR_DISCORD_TOKEN`

7. `python3 bot.py`
