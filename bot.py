import os
import time
import datetime
import threading
import socket
import select
import asyncio
import queue
import json
import discord
from discord import app_commands
from discord.ext import tasks
from enum import Enum
from queue import Queue
from rcon import rcon
from threading import Thread, Lock

class JoinStatus(Enum):
    DISCONNECTED = 0
    CONNECTED = 1

class TestChange:
    def __init__(self, change, author):
        self.change = change
        self.author = author

class Tester:
    def __init__(self, networkid:str, name:str, jointime:int, status:JoinStatus):
        self.networkid = networkid
        self.name = name
        self.jointime = jointime
        self.endtime = -1
        self.status = status

class PlayerJoinStatus:
    def __init__(self, name:str, networkid:str, status:JoinStatus) -> None:
        self.name = name
        self.networkid = networkid
        self.status = status

class PlayerInfo:
    def __init__(self, name:str, networkid:str, userid:int) -> None:
        self.name = name
        self.networkid = networkid # SteamID or BOT
        self.userid = userid

class RCONInfo:
    def __init__(self, address:str, port:int, password:str, comment:str = '') -> None:
        self.address = address
        self.port = port
        self.password = password
        self.comment = comment

CONFIG_FILE_NAME = "config.json"
TEST_CHANGES_FILE_NAME = "test_changes.json"

bTestActive = False
test_changes = []
testers:dict = {}
testers_mutex:Lock = Lock()
rcon_infos_mutex:Lock = Lock()
rcon_infos:dict = {}

token = os.getenv("DISCORD_TOKEN")

testing_channel_id = os.getenv("PLAYTEST_CHANNELID", "-1")

try:
    testing_channel_id = int(testing_channel_id)
except:
    testing_channel_id = -1

if testing_channel_id == -1:
    print("WARNING: No channel ID specified to forward playtest messages to, please set PLAYTEST_CHANNELID environment variable.")

try:
    # TODO: Perhaps move the above environment variable stuff to this config?
    file = open(CONFIG_FILE_NAME, 'r')
    data:dict = json.load(file)

    rcon_info:dict
    for rcon_info in data["rcon"]:
        # Append RCON information instead of creating an instance of 'rcon'
        # As we don't know when a server is gonna go offline
        # NOTE: Don't need rcon_infos_mutex here, we're starting up
        address:str = rcon_info["address"]
        port:int = rcon_info["port"]
        password:str = rcon_info["password"]
        comment:str = rcon_info["comment"]

        rcon_infos[f"{address}:{port}"] = RCONInfo(
            address,
            port,
            password,
            comment
        )

except IOError as e:
    print(f"Failed to load config.json: {e}")
    pass

def save_config() -> bool:
    config:dict = {
        "rcon": []
    }

    rcon_list:list = config["rcon"]

    rcon_infos_mutex.acquire()
    rcon_info:RCONInfo
    for rcon_info in rcon_infos.values():
        rcon_list.append(
            {
                "address": rcon_info.address,
                "port": rcon_info.port,
                "password": rcon_info.password,
                "comment": rcon_info.comment
            }
        )
    rcon_infos_mutex.release()

    try:
        file = open(CONFIG_FILE_NAME, 'w')
        file.write(json.dumps(config, indent=4))
        file.close()
    except IOError as e:
        print(f"Failed to save config: {e}")
        return False
    
    return True

def save_test_changes() -> None:
    data:dict = {"changes": []}
    changes:list = data["changes"]

    change:TestChange
    for change in test_changes:
        changes.append(
            {
                "author": change.author,
                "change": change.change
            }
        )
    try:
        file = open(TEST_CHANGES_FILE_NAME, 'w')
        file.write(json.dumps(data, indent=4))
        
        file.close()
    except IOError as e:
        print(f"Failed to save test changes: {e}")

def load_test_changes() -> None:
    try:
        file = open(TEST_CHANGES_FILE_NAME, 'r')
        data:dict = json.load(file)
        test_changes.clear()

        changes:list = data["changes"]
        change:dict

        for change in changes:
            test_changes.append(TestChange(change["change"], change["author"]))
        
    except IOError as e:
        pass # Failure is acceptable here

load_test_changes()

intents = discord.Intents.default()

player_status_queue:Queue = Queue()

class RCONThread(Thread):
    def __init__(self):
        super().__init__()
        self.should_stop = threading.Event()
    
    def stop(self):
        self.should_stop.set()

    def run(self) -> None:
        while not self.should_stop.is_set():
            player_data:dict = {}

            rcon_infos_mutex.acquire()
            for info in rcon_infos.values():
                player_info:list = rcon(info.address, info.port, info.password, silent=True).exec_command("player_info").splitlines()

                NETWORKID:int = 0
                USERID:int = 1

                for line in player_info:
                    split_line:list = line.split()
                    if not split_line[NETWORKID].startswith("[U:"):
                        continue
                    
                    player_name_start:int = len(split_line[NETWORKID]) + len(split_line[USERID]) + 2 # Plus 2 for spaces
                    player_data[split_line[NETWORKID]] = PlayerInfo(
                        line[player_name_start:],
                        split_line[NETWORKID],
                        split_line[USERID]
                    )
            
            rcon_infos_mutex.release()
            testers_mutex.acquire()

            # Do all this after gathering player data or else multiple servers will cause a join/disconnect loop
            for networkid in testers:
                if networkid not in player_data:
                    tester:Tester = testers[networkid]
                    if tester.status != JoinStatus.DISCONNECTED:
                        player_status_queue.put(PlayerJoinStatus(tester.name, tester.networkid, JoinStatus.DISCONNECTED))
            
            for networkid in player_data:
                player_info:PlayerInfo = player_data[networkid]
                if networkid not in testers:
                    player_status_queue.put(PlayerJoinStatus(player_info.name, player_info.networkid, JoinStatus.CONNECTED))
                else:
                    tester:Tester = testers[networkid]
                    if tester.status != JoinStatus.CONNECTED:
                        player_status_queue.put(PlayerJoinStatus(player_info.name, player_info.networkid, JoinStatus.CONNECTED))


            testers_mutex.release()
            time.sleep(1.0)

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

        # TODO: It should be possible to ditch using a thread and opt for coroutines with async/await
        # The issue is the socket API on its own is not asynchronous
        rcon_thread:RCONThread = RCONThread()
        rcon_thread.start()

        # TODO: We may want to buffer join/disconnect messages before sending them in Discord

        while not self.is_closed() and bTestActive:
            if player_status_queue.qsize() > 0:
                try:
                    player_status:PlayerJoinStatus = player_status_queue.get_nowait()
                    testers_mutex.acquire()

                    if player_status.status == JoinStatus.CONNECTED:
                        announce_join:bool = False

                        if player_status.networkid not in testers:
                            testers[player_status.networkid] = Tester(
                                networkid=player_status.networkid,
                                name=player_status.name,
                                jointime=int(time.time()),
                                status=JoinStatus.CONNECTED
                            )

                            announce_join = True
                        else:
                            tester:Tester = testers[player_status.networkid]
                            if tester.status != JoinStatus.CONNECTED:
                                tester.status = JoinStatus.CONNECTED
                                announce_join = True
                    
                        if announce_join and testing_channel_id != -1:
                            msg:str = f"{player_status.name} joined the test."
                            await self.get_channel(testing_channel_id).send(msg)
                    
                    if player_status.status == JoinStatus.DISCONNECTED:
                        if player_status.networkid in testers:
                            tester:Tester = testers[player_status.networkid]
                            tester.endtime = time.time()
                            tester.status = JoinStatus.DISCONNECTED

                            if testing_channel_id != -1:
                                msg:str = f"{player_status.name} left the test."
                                await self.get_channel(testing_channel_id).send(msg)
                    
                    testers_mutex.release()
                except queue.Empty:
                    pass

            await asyncio.sleep(1.0)
        
        rcon_thread.stop()
        rcon_thread.join()

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

    save_test_changes()

    await interaction.response.send_message(msg)

# /tce
@tree.command(guild=None, name='tce', description='Edit existing test change by list index. Ex: /tce 0 Fix a typo...')
async def slash_tce(interaction: discord.Interaction, index: int, change: str):
    if index >= len(test_changes) or index < 0:
        msg = "Index out of range."
    else:
        test_changes[index].change = change
        msg = f"Edited change #{index}: {test_changes[index].change}"
    
    save_test_changes()

    await interaction.response.send_message(msg)

# /tcr
@tree.command(guild=None, name='tcr', description='Remove test change by list index. Ex: /tcr 1')
async def slash_tcr(interaction: discord.Interaction, index: int):
    if index >= len(test_changes) or index < 0:
        msg = "Index out of range."
    else:
        msg = f"Removed change: {test_changes[index].change}"
        test_changes.pop(index)

    save_test_changes()

    await interaction.response.send_message(msg)

# /tcpurge
@tree.command(guild=None, name='tcpurge', description='Remove all changes.')
async def slash_tcpurge(interaction: discord.Interaction):
    test_changes.clear()
    msg = "All changes cleared."

    save_test_changes()

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
        testers.clear() # Shouldn't need testers_mutex here
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

        testers_mutex.acquire()
        for x in testers.values():
            if x.endtime == -1:
                x.endtime = int(time.time())

            timespent = x.endtime - x.jointime
            timestr = str(datetime.timedelta(seconds=timespent))
            msg += f"{x.name} was present for {timestr}\n"

        msg += "```"
        bTestActive = False
        testers.clear()
        testers_mutex.release()

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

# /showts
@tree.command(guild=None, name="showts", description="Show registered test servers")
async def slash_showts(interaction: discord.Interaction):
    msg = f"Currently registered test servers:\n```\n"
    rcon_infos_mutex.acquire()
    rcon_info:RCONInfo

    # TODO: Should maybe add message splitting like test changes
    # But I doubt we'll ever have that many test servers
    for rcon_info in rcon_infos.values():
        msg += f"{rcon_info.address}:{rcon_info.port} => {rcon_info.comment}\n"

    rcon_infos_mutex.release()

    msg += "```"
    await interaction.response.send_message(msg)

# /addts
@tree.command(guild=None, name="addts", description="Add test server for tracking Ex: /addts ip port \"password\" \"server name\"")
async def slash_addts(interaction: discord.Interaction, address:str, port:int, password:str, comment:str):
    if len(password) == 0:
        await interaction.response.send_message(f"No password provided", ephemeral=True)
        return
    
    if len(comment) == 0:
        await interaction.response.send_message(f"No server name provided", ephemeral=True)
        return

    rcon_infos_mutex.acquire()
    if f"{address}:{port}" in rcon_infos:
        await interaction.response.send_message(f"{address}:{port} already in server list", ephemeral=True)
        rcon_infos_mutex.release()
        return
    
    if port < 0 or port > 65535:
        await interaction.response.send_message(f"{port} is not a valid port", ephemeral=True)
        rcon_infos_mutex.release()
        return
    
    rcon_infos[f"{address}:{port}"] = RCONInfo(address, port, password, comment)
    rcon_infos_mutex.release()

    msg:str = f"Added {address}:{port} => {comment}"

    if not save_config():
        msg += "\nWARNING: Failed to save config, server won't be available on bot reboot"

    await interaction.response.send_message(msg, ephemeral=True)

# /remts
@tree.command(guild=None, name="remts", description="Remove a test server from tracking Ex: /remts ip port")
async def slash_remts(interaction: discord.Interaction, address:str, port:int):
    full_address = f"{address}:{port}"
    was_removed:bool = False
    rcon_infos_mutex.acquire()

    if full_address in rcon_infos:
        rcon_infos.pop(full_address)
        was_removed = True
    
    rcon_infos_mutex.release()

    if was_removed:
        msg = f"Removed {address}:{port} from test tracking"

        if not save_config():
            msg += "\nWARNING: Failed to save config, server won't be available on bot reboot"

        await interaction.response.send_message(msg)
    else:
        await interaction.response.send_message(f"{address}:{port} was not found")


client.run(token)
