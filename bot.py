import os
import time
import datetime
import discord
from discord import app_commands

class TestChange:
    def __init__(self, change, author):
        self.change = change
        self.author = author

class Tester:
    def __init__(self, id, name, jointime):
        self.id = id
        self.name = name
        self.jointime = jointime
        self.endtime = -1

bTestActive = False
test_changes = []
testers = []

token = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()

class aclient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.synced = False

    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:
            await tree.sync(guild=None)
            self.synced = True
        print(f"We have logged in as {self.user}.")

client = aclient()

tree = app_commands.CommandTree(client)

# test slash commands
@tree.command(guild=None, name='misery', description='Increase misery. (Use with care!)')
async def slash_misery(interaction: discord.Interaction):
    await interaction.response.send_message(f"Little Beepo's misery is increasing.", ephemeral=True)

# /tcl
@tree.command(guild=None, name='tcl', description='List changes for next test.')
async def slash_tcl(interaction: discord.Interaction):
    if len(test_changes) == 0:
        msg = "Changes to test:\nNone.\n"
    else:
        bSplit = False
        tag = "```"
        tagSize = 2 * len(tag)
        header = "Changes to test:\n"
        msgMax = 2000 - (len(header) - tagSize)
        n = 0
        content = ""

        for x in test_changes:
            entry = f"{n}. " + x.change + f" (Added by: {x.author})\n"
            n += 1

            if len(content) + len(entry) >= msgMax:
                if bSplit == False:
                    msg = header + tag + content + tag
                else:
                    msg = tag + content + tag

                await interaction.response.send_message(msg, ephemeral=False)

                bSplit = True
                content = ""

            content += entry

        if bSplit == False:
            msg = header + tag + content + tag
        elif len(content) > 0:
            msg = tag + content + tag

    await interaction.response.send_message(msg, ephemeral=False)

# /tca
@tree.command(guild=None, name='tca', description='Add test change by list index. Ex: /tca Modified a model, map, functionality, etc...')
async def slash_tca(interaction: discord.Interaction, change: str):
    new_change = TestChange(change, interaction.user.display_name)
    test_changes.append(new_change)
    msg = f"Added change for next test: {new_change.change}"

    await interaction.response.send_message(msg)

# /tce
@tree.command(guild=None, name='tce', description='Edit existing test change by list index. Ex: /tce 0 Fix a typo...')
async def slash_tce(interaction: discord.Interaction, index: int, change: str):
    if index >= len(test_changes) or index < 0:
        msg = "Index out of range."
    else:
        test_changes[index].change = change
        msg = f"Edited change #{index}: {test_changes[index].change}"

    await interaction.response.send_message(msg)

# /tcr
@tree.command(guild=None, name='tcr', description='Remove test change by list index. Ex: /tcr 1')
async def slash_tcr(interaction: discord.Interaction, index: int):
    if index >= len(test_changes) or index < 0:
        msg = "Index out of range."
    else:
        msg = f"Removed change: {test_changes[index].change}"
        test_changes.pop(index)

    await interaction.response.send_message(msg)

# /tcpurge
@tree.command(guild=None, name='tcpurge', description='Remove all changes.')
async def slash_tcpurge(interaction: discord.Interaction):
    test_changes.clear()
    msg = "All changes cleared."

    await interaction.response.send_message(msg)

# /tstart
@tree.command(guild=None, name='tstart', description='Start tracking a test.')
async def slash_tstart(interaction: discord.Interaction):
    global bTestActive
    if bTestActive == True:
        msg = "Test already active, stop it first."
    else:
        msg = "Test started, use /join command to check in."
        bTestActive = True
        testers.clear()

    await interaction.response.send_message(msg)

# /tstop
@tree.command(guild=None, name='tstop', description='Stop tracking a test.')
async def slash_tstop(interaction: discord.Interaction):
    global bTestActive
    if bTestActive == False:
        msg = "No test active, start it first."
    else:
        date_object = datetime.date.today()
        msg = f"Today's test has ended.\nPlayers in attendance for {date_object}\n```\n"

        for x in testers:
            if x.endtime == -1:
                x.endtime = int(time.time())

            timespent = x.endtime - x.jointime
            timestr = str(datetime.timedelta(seconds=timespent))
            msg += f"{x.name} was present for {timestr}\n"

        msg += "```"
        bTestActive = False
        testers.clear()

    await interaction.response.send_message(msg)

# /join
@tree.command(guild=None, name='join', description='Join an active test.')
async def slash_join(interaction: discord.Interaction):
    global bTestActive
    if bTestActive == False:
        msg = "No test active."
    else:
        bJoined = False

        for x in testers:
            if x.id == interaction.user.id:
                if x.endtime == -1:
                    msg = "You've already joined the test."
                else:
                    x.endtime = -1
                    msg = f"{interaction.user.display_name} rejoined the test."

                bJoined = True

        if bJoined == False:
            now = int(time.time())
            entry = Tester(interaction.user.id,
                           interaction.user.display_name, now)
            testers.append(entry)
            msg = f"{interaction.user.display_name} joined the test."

    await interaction.response.send_message(msg)

# /leave
@tree.command(guild=None, name='leave', description='Leave an active test.')
async def slash_leave(interaction: discord.Interaction):
    global bTestActive
    if bTestActive == False:
        msg = "No test active."
    else:
        for x in testers:
            if x.id == interaction.user.id:
                x.endtime = int(time.time())

        msg = f"{interaction.user.display_name} left the test."

    await interaction.response.send_message(msg)

# /pingrole
# hardcoded right now :)
@tree.command(guild=None, name='pingrole', description='Mention tester role.')
async def slash_pingrole(interaction: discord.Interaction):
    role = discord.utils.find(lambda r: r.name == 'Test Coordinator', interaction.guild.roles)
    if role in interaction.user.roles:
        msg = f"<@&307979412903821323> <@&1049422754602025053> Test starting soon."
    else:
        msg = "You have no access to this command."
    
    await interaction.response.send_message(msg)

client.run(token)
