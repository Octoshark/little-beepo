import os
import time
import json
import threading
import locks
from threading import Thread
from queue import Queue
from enum import Enum
from rcon import rcon

TEST_CHANGES_FILE_NAME = "test_changes.json"

test_active:bool = False
test_changes:list = []
testers:dict = {}
rcon_infos:dict = {}
player_status_queue:Queue = Queue()

testing_channel_id = os.getenv("PLAYTEST_CHANNELID", "-1")

try:
    testing_channel_id = int(testing_channel_id)
except:
    testing_channel_id = -1

if testing_channel_id == -1:
    print("WARNING: No channel ID specified to forward playtest messages to, please set PLAYTEST_CHANNELID environment variable.")

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

class RCONThread(Thread):
    def __init__(self):
        super().__init__()
        self.should_stop = threading.Event()
    
    def stop(self):
        self.should_stop.set()

    def run(self) -> None:
        while not self.should_stop.is_set():
            player_data:dict = {}

            locks.rcon.acquire()
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
            
            locks.rcon.release()
            locks.testers.acquire()

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


            locks.testers.release()
            time.sleep(1.0)


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