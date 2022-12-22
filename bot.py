import time
import datetime
import asyncio
import queue
import config
import testing
import locks
import threads
import random
import discord
from discord import app_commands
from queue import Queue

from testing import (
    JoinStatus,
    TestChange,
    Tester,
    PlayerJoinStatus,
    RCONInfo,
    RCONThread
)

intents = discord.Intents.default()

class aclient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.synced:bool = False
        self.task_playtest:asyncio.Task

    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:
            await tree.sync(guild=None)
            self.synced = True
        print(f"We have logged in as {self.user}.")
    
    async def handle_task_playtest(self):

        # TODO: It should be possible to ditch using a thread and opt for coroutines with async/await
        # The issue is the socket API on its own is not asynchronous

        msg:str = ''

        threads.rcon = RCONThread()
        threads.rcon.start()

        while testing.test_active:
            if testing.player_status_queue.qsize() == 0:
                if len(msg) > 0:
                    # TODO: We should probably handle message splitting, but hopefully we won't exceed 2000 characters
                    await self.get_channel(testing.testing_channel_id).send(msg)
                    msg = ''
                await asyncio.sleep(1.0)
                continue

            try:
                player_status:PlayerJoinStatus = testing.player_status_queue.get_nowait()
                locks.testers.acquire()

                if player_status.status == JoinStatus.CONNECTED:
                    announce_join:bool = False

                    if player_status.networkid not in testing.testers:
                        testing.testers[player_status.networkid] = Tester(
                            networkid=player_status.networkid,
                            name=player_status.name,
                            jointime=int(time.time()),
                            status=JoinStatus.CONNECTED
                        )

                        announce_join = True
                    else:
                        tester:Tester = testing.testers[player_status.networkid]
                        if tester.status != JoinStatus.CONNECTED:
                            tester.status = JoinStatus.CONNECTED
                            announce_join = True
                
                    if announce_join and testing.testing_channel_id != -1:
                        msg += f"{player_status.name} joined the test.\n"
                
                if player_status.status == JoinStatus.DISCONNECTED:
                    if player_status.networkid in testing.testers:
                        tester:Tester = testing.testers[player_status.networkid]
                        tester.endtime = int(time.time())
                        tester.status = JoinStatus.DISCONNECTED

                        if testing.testing_channel_id != -1:
                            msg += f"{player_status.name} left the test.\n"
                
                locks.testers.release()
            except queue.Empty:
                pass

    # have some grease?
    misery_level:int = 0

client = aclient()

tree = app_commands.CommandTree(client)

# /misery
@tree.command(guild=None, name='misery', description='Increase misery. (Use with care!)')
async def slash_misery(interaction: discord.Interaction):
    client.misery_level += 1

    msg = f"Misery Level: {client.misery_level}"
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=msg))

    await interaction.response.send_message(f"Little Beepo's misery is increasing.", ephemeral=True)

# /givegrease
@tree.command(guild=None, name='givegrease', description='Decrease misery by giving Little Beepo some grease from the stovetop.')
async def slash_givegrease(interaction: discord.Interaction):
    # purposely not clamped :)
    client.misery_level -= 1

    msg = f"Misery Level: {client.misery_level}"
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=msg))

    await interaction.response.send_message(f"Little Beepo's misery is decreasing.", ephemeral=True)

# /tcl
@tree.command(guild=None, name='tcl', description='List changes for next test.')
async def slash_tcl(interaction: discord.Interaction):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    if len(testing.test_changes) == 0:
        msg = "Changes to test:\nNone.\n"
    else:
        bSplit = False
        tag = "```"
        tagSize = 2 * len(tag)
        header = "Changes to test:\n"
        msgMax = 2000 - (len(header) - tagSize)
        n = 0
        content = ""

        for x in testing.test_changes:
            entry = f"{n}. " + x.change + f" (Added by: {x.author})\n"
            n += 1

            if len(content) + len(entry) >= msgMax:
                if bSplit == False:
                    msg = header + tag + content + tag
                else:
                    msg = tag + content + tag

                # FIXME: Responding to the same interaction multiple times raises exceptions
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
@tree.command(guild=None, name='tca', description='Add test change. Ex: /tca Modified a model, map, functionality, etc...')
async def slash_tca(interaction: discord.Interaction, change: str):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return
    
    new_change = TestChange(change, interaction.user.display_name)
    testing.test_changes.append(new_change)
    msg = f"Added change for next test: {new_change.change}"

    testing.save_test_changes()

    await interaction.response.send_message(msg)

# /tce
@tree.command(guild=None, name='tce', description='Edit existing test change by list index. Ex: /tce 0 Fix a typo...')
async def slash_tce(interaction: discord.Interaction, index: int, change: str):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    if index >= len(testing.test_changes) or index < 0:
        msg = "Index out of range."
    else:
        testing.test_changes[index].change = change
        msg = f"Edited change #{index}: {testing.test_changes[index].change}"
    
    testing.save_test_changes()

    await interaction.response.send_message(msg)

# /tcr
@tree.command(guild=None, name='tcr', description='Remove test change by list index. Ex: /tcr 1')
async def slash_tcr(interaction: discord.Interaction, index: int):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    if index >= len(testing.test_changes) or index < 0:
        msg = "Index out of range."
    else:
        msg = f"Removed change: {testing.test_changes[index].change}"
        testing.test_changes.pop(index)

    testing.save_test_changes()

    await interaction.response.send_message(msg)

# /tcpurge
@tree.command(guild=None, name='tcpurge', description='Remove all changes.')
async def slash_tcpurge(interaction: discord.Interaction):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    role = discord.utils.find(lambda r: r.name == config.coordinator_role_name, interaction.guild.roles)
    if role not in interaction.user.roles:
        await interaction.response.send_message(config.msg_access_denied, ephemeral=True)
        return

    testing.test_changes.clear()
    msg = "All changes cleared."

    testing.save_test_changes()

    await interaction.response.send_message(msg)

# /tstart
@tree.command(guild=None, name='tstart', description='Start tracking a test.')
async def slash_tstart(interaction: discord.Interaction):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    role = discord.utils.find(lambda r: r.name == config.coordinator_role_name, interaction.guild.roles)
    if role not in interaction.user.roles:
        await interaction.response.send_message(config.msg_access_denied, ephemeral=True)
        return

    if testing.test_active == True:
        msg = "Test already active, stop it first."
    else:
        msg = "Test started."
        testing.test_active = True
        testing.testers.clear() # Shouldn't need locks.testers here
        client.task_playtest = client.loop.create_task(client.handle_task_playtest())

    await interaction.response.send_message(msg)

# /tstop
@tree.command(guild=None, name='tstop', description='Stop tracking a test.')
async def slash_tstop(interaction: discord.Interaction):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    role = discord.utils.find(lambda r: r.name == config.coordinator_role_name, interaction.guild.roles)
    if role not in interaction.user.roles:
        await interaction.response.send_message(config.msg_access_denied, ephemeral=True)
        return

    if testing.test_active == False:
        msg = "No test active, start it first."
    else:
        date_object = datetime.date.today()
        msg = f"Today's test has ended.\nPlayers in attendance for {date_object}\n```\n"

        testing.test_active = False

        try:
            client.task_playtest.cancel()
        except:
            pass

        if threads.rcon.is_alive():
            threads.rcon.stop()
            threads.rcon.join()
        
        testing.player_status_queue.queue.clear()

        locks.testers.acquire()
        for x in testing.testers.values():
            if x.endtime == -1:
                x.endtime = int(time.time())

            timespent = x.endtime - x.jointime
            timestr = str(datetime.timedelta(seconds=timespent))
            msg += f"{x.name} was present for {timestr}\n"

        msg += "```"
        testing.testers.clear()
        locks.testers.release()

    await interaction.response.send_message(msg)

# /pingrole
# hardcoded right now :)
@tree.command(guild=None, name='pingrole', description='Mention tester role.')
async def slash_pingrole(interaction: discord.Interaction):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    role = discord.utils.find(lambda r: r.name == config.coordinator_role_name, interaction.guild.roles)
    if role not in interaction.user.roles:
        await interaction.response.send_message(config.msg_access_denied, ephemeral=True)
        return

    msg:str = ''

    for role_id in config.ping_roles:
        msg += f"<@&{role_id}> "
    
    msg += "Test starting soon."
    await interaction.response.send_message(msg, allowed_mentions=discord.AllowedMentions(roles=True))

# /showts
@tree.command(guild=None, name="showts", description="Show registered test servers")
async def slash_showts(interaction: discord.Interaction):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    msg = f"Currently registered test servers:\n```\n"
    locks.rcon.acquire()
    rcon_info:RCONInfo

    # TODO: Should maybe add message splitting like test changes
    # But I doubt we'll ever have that many test servers
    for rcon_info in testing.rcon_infos.values():
        msg += f"{rcon_info.address}:{rcon_info.port} => {rcon_info.comment}\n"

    locks.rcon.release()

    msg += "```"
    await interaction.response.send_message(msg)

# /addts
@tree.command(guild=None, name="addts", description="Add test server for tracking Ex: /addts ip port \"password\" \"server name\"")
async def slash_addts(interaction: discord.Interaction, address:str, port:int, password:str, comment:str):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    role = discord.utils.find(lambda r: r.name == config.coordinator_role_name, interaction.guild.roles)
    if role not in interaction.user.roles:
        await interaction.response.send_message(config.msg_access_denied, ephemeral=True)
        return
    
    if len(password) == 0:
        await interaction.response.send_message(f"No password provided", ephemeral=True)
        return
    
    if len(comment) == 0:
        await interaction.response.send_message(f"No server name provided", ephemeral=True)
        return

    locks.rcon.acquire()
    if f"{address}:{port}" in testing.rcon_infos:
        await interaction.response.send_message(f"{address}:{port} already in server list", ephemeral=True)
        locks.rcon.release()
        return
    
    if port < 0 or port > 65535:
        await interaction.response.send_message(f"{port} is not a valid port", ephemeral=True)
        locks.rcon.release()
        return
    
    testing.rcon_infos[f"{address}:{port}"] = RCONInfo(address, port, password, comment)
    locks.rcon.release()

    msg:str = f"Added {address}:{port} => {comment}"

    if not config.save_config():
        msg += "\nWARNING: Failed to save config, server won't be available on bot reboot"

    await interaction.response.send_message(msg, ephemeral=True)

# /remts
@tree.command(guild=None, name="remts", description="Remove a test server from tracking Ex: /remts ip port")
async def slash_remts(interaction: discord.Interaction, address:str, port:int):
    if interaction.channel_id != testing.testing_channel_id:
        await interaction.response.send_message(config.msg_bad_channel, ephemeral=True)
        return

    role = discord.utils.find(lambda r: r.name == config.coordinator_role_name, interaction.guild.roles)
    if role not in interaction.user.roles:
        await interaction.response.send_message(config.msg_access_denied, ephemeral=True)
        return

    full_address = f"{address}:{port}"
    was_removed:bool = False
    locks.rcon.acquire()

    if full_address in testing.rcon_infos:
        testing.rcon_infos.pop(full_address)
        was_removed = True
    
    locks.rcon.release()

    if was_removed:
        msg = f"Removed {address}:{port} from test tracking"

        if not config.save_config():
            msg += "\nWARNING: Failed to save config, server won't be available on bot reboot"

        await interaction.response.send_message(msg)
    else:
        await interaction.response.send_message(f"{address}:{port} was not found")

# /8ball
@tree.command(guild=None, name="8ball", description="Ask the magic 8 ball questions")
async def slash_8ball(interaction: discord.Interaction, question:str):
    # TODO (Maybe): We could rig this and make neutral/negative responses more likely depending on misery level
    responses:list = [
        "It is certain.",
        "It is decidedly so.",
        "Without a doubt.",
        "Yes definitely.",
        "You may rely on it.",
        "As I see it, yes.",
        "Most likely.",
        "Outlook good.",
        "Yes.",
        "Signs point to yes.",
        
        "Reply hazy, try again.",
        "Ask again later.",
        "Better not tell you now.",
        "Cannot predict now.",
        "Concentrate and ask again.",

        "Don't count on it.",
        "My reply is no.",
        "My sources say no.",
        "Outlook not so good.",
        "Very doubtful."
    ]
    
    response:int = random.randint(0, len(responses) - 1)
    msg:str = f'"{question}"\n{responses[response]}'

    await interaction.response.send_message(msg)


def main():
    # Was gonna try to add the ability to reboot the bot, but this Discord API just raises exceptions no matter what
    # At least this is cleaner than doing things in global scope
    config.init()
    client.run(config.discord_token)

if __name__ == "__main__":
    main()
