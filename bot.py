import os
import time
import datetime
import threading
import socket
import select
import asyncio
import queue
import discord
from discord import app_commands
from discord.ext import tasks
from enum import Enum
from queue import Queue

class TestChange:
    def __init__(self, change, author):
        self.change = change
        self.author = author

class Tester:
    def __init__(self, steamid:str, name:str, jointime:int):
        self.steamid = steamid
        self.name = name
        self.jointime = jointime
        self.endtime = -1

class JoinStatus(Enum):
    DISCONNECTED = 0
    CONNECTED = 1

class PlayerJoinStatus:
    def __init__(self, name:str, steamid:str, status:JoinStatus) -> None:
        self.name = name
        self.steamid = steamid
        self.status = status

class PlayerInfo:
    def __init__(self, name:str, playerid:str, userid:int) -> None:
        self.name = name
        self.playerid = playerid # SteamID or BOT
        self.userid = userid

bTestActive = False
test_changes = []
testers:dict = {}

token = os.getenv("DISCORD_TOKEN")

listen_ip = os.getenv("LOGADDRESS_IP", "0.0.0.0") # 0.0.0.0 should bind to all addresses and work fine in most cases. If not, specify an appropriate local IP
listen_port = os.getenv("LOGADDRESS_PORT", "-1")

try:
    listen_port = int(listen_port)
except:
    listen_port = -1

if listen_port == -1:
    print("WARNING: No valid port specified for logaddress protocol, please set LOGADDRESS_PORT environment variable.")

testing_channel_id = os.getenv("PLAYTEST_CHANNELID", "-1")

try:
    testing_channel_id = int(testing_channel_id)
except:
    testing_channel_id = -1

if testing_channel_id == -1:
    print("WARNING: No channel ID specified to forward playtest messages to, please set PLAYTEST_CHANNELID environment variable.")

intents = discord.Intents.default()

def get_player_info_from_log(log_string:str) -> PlayerInfo:
    # This is a little tricky because the player name could have quotes and angle brackets
    # So we have to be careful how we use them to figure out the player name
    
    # Format appears to be "Player Name<USERID><STEAMID or BOT><TEAMNAME>"
    # Connection messages contain an empty team name, so it will be <>
    # Disconnections and team joins will contain the team name

    # Example connections
    # L 12/05/2022 - 20:42:40: "Sveinn<9><BOT><>" connected, address "none"
    # L 12/05/2022 - 21:00:06: "Spirrwell<11><[U:1:36987536]><>" connected, address "192.168.1.3:27005"

    # Example disconnections
    # L 12/05/2022 - 20:42:40: "Sveinn<9><BOT><Vikings>" disconnected (reason "Bot kicked by server")
    # L 12/05/2022 - 21:00:27: "Spirrwell<11><[U:1:36987536]><Unassigned>" disconnected (reason "Disconnect by user.")
    team_string_end = log_string.rfind(">")
    team_string_begin = log_string.rfind("<", 0, team_string_end) + 1

    playerid_end = log_string.rfind(">", 0, team_string_begin)
    playerid_start = log_string.rfind("<", 0, playerid_end) + 1

    userid_end = log_string.rfind(">", 0, playerid_start)
    userid_start = log_string.rfind("<", 0, userid_end) + 1

    playername_end = userid_start - 1
    playername_start = log_string.find('"') + 1

    try:
        playerid:str = log_string[playerid_start:playerid_end]
        userid:int = int(log_string[userid_start:userid_end])
        playername:str = log_string[playername_start:playername_end]
        return PlayerInfo(playername, playerid, userid)
    except:
        return PlayerInfo('', '', -1)


player_status_queue:Queue = Queue()

# This is the only decent documentation I could find of this protocol:
# https://github.com/jackwilsdon/logaddress-protocol/blob/master/protocol.md
def logaddress_listen_thread(stop) -> None:
    if listen_port == -1:
        return

    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    listener.bind((listen_ip, listen_port))
    listener.setblocking(False)

    while not stop():
        ready_to_read, ready_to_write, in_error = select.select(
            [listener],
            [],
            [],
            1.0
        )

        if len(ready_to_read) == 0:
            continue
        
        data, address = listener.recvfrom(65535) # Receive UDP max packet size

        # Packet should theoretically always be greater than 6 bytes long, and should always start with 0xFFFFFFFF
        if len(data) > 6 and int.from_bytes(data[0:4], "little", signed=True) == -1:
            type = data[4]

            if type == 0x52: # Default is 0x52, 0x53 is used when a secret is set which we don't support yet (sv_logsecret)
                body:str = data[5:].decode("utf-8")[0:-1] # Decode and discard null terminator
            
				# FIXME: This responds to chat messages as well!!
                if body.find("disconnected") != -1:
                    player_info:PlayerInfo = get_player_info_from_log(body)
                    if not player_info.userid == -1 and not player_info.playerid == "BOT":
                        player_status_queue.put(PlayerJoinStatus(player_info.name, player_info.playerid, JoinStatus.DISCONNECTED))
                elif body.find("connected") != -1:
                    player_info:PlayerInfo = get_player_info_from_log(body)
                    if not player_info.userid == -1 and not player_info.playerid == "BOT":
                        player_status_queue.put(PlayerJoinStatus(player_info.name, player_info.playerid, JoinStatus.CONNECTED))

    

class aclient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.synced = False
        self.task_playtest = None

    async def on_ready(self):
        await self.wait_until_ready()
        if not self.synced:
            await tree.sync(guild=None)
            self.synced = True
        print(f"We have logged in as {self.user}.")
    
    async def handle_task_playtest(self):
        stop_thread = False # TODO: Use threading.Event instead

		# TODO: It should be possible to ditch using a thread and opt for coroutines with async/await
		# The issue is the socket API on its own is not asynchronous
        listen_thread = threading.Thread(target=logaddress_listen_thread, args=(lambda: stop_thread,))
        listen_thread.start()

        while not self.is_closed() and bTestActive:
            if player_status_queue.qsize() > 0:
                try:
                    player_status:PlayerJoinStatus = player_status_queue.get_nowait()

                    if player_status.status == JoinStatus.CONNECTED:
                        testers[player_status.steamid] = Tester(
                            steamid=player_status.steamid,
                            name=player_status.name,
                            jointime=int(time.time())
                        )

                        if testing_channel_id != -1:
                            msg:str = f"{player_status.name} joined the test."
                            await self.get_channel(testing_channel_id).send(msg)
                    
                    if player_status.status == JoinStatus.DISCONNECTED:
                        if player_status.steamid in testers:
                            testers[player_status.steamid].endtime = time.time()

                            if testing_channel_id != -1:
                                msg:str = f"{player_status.name} left the test."
                                await self.get_channel(testing_channel_id).send(msg)
                except queue.Empty:
                    pass

            await asyncio.sleep(1.0)
        
        stop_thread = True
        listen_thread.join()

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
        msg = "Test started."
        bTestActive = True
        testers.clear()
        client.task_playtest = client.loop.create_task(client.handle_task_playtest())

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

        for x in testers.values():
            if x.endtime == -1:
                x.endtime = int(time.time())

            timespent = x.endtime - x.jointime
            timestr = str(datetime.timedelta(seconds=timespent))
            msg += f"{x.name} was present for {timestr}\n"

        msg += "```"
        bTestActive = False
        testers.clear()

    await interaction.response.send_message(msg)

'''
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
'''

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
