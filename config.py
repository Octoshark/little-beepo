import os
import json
import locks
import testing
from testing import (
    RCONInfo
)

CONFIG_FILE_NAME = "config.json"

discord_token:str = os.getenv("DISCORD_TOKEN")

# TODO: Move to config?
coordinator_role_name:str = "Test Coordinator"

msg_access_denied:str = "You have no access to this command."
msg_bad_channel:str = "Command not allowed in this channel."

def load_config() -> None:
    try:
        # TODO: Perhaps move the above environment variable stuff to this config?
        file = open(CONFIG_FILE_NAME, 'r')
        data:dict = json.load(file)

        rcon_info:dict
        for rcon_info in data["rcon"]:
            # Append RCON information instead of creating an instance of 'rcon'
            # As we don't know when a server is gonna go offline
            # NOTE: Don't need rcon lock here, we're starting up
            address:str = rcon_info["address"]
            port:int = rcon_info["port"]
            password:str = rcon_info["password"]
            comment:str = rcon_info["comment"]

            testing.rcon_infos[f"{address}:{port}"] = RCONInfo(
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

    locks.rcon.acquire()
    rcon_info:RCONInfo
    for rcon_info in testing.rcon_infos.values():
        rcon_list.append(
            {
                "address": rcon_info.address,
                "port": rcon_info.port,
                "password": rcon_info.password,
                "comment": rcon_info.comment
            }
        )
    locks.rcon.release()

    try:
        file = open(CONFIG_FILE_NAME, 'w')
        file.write(json.dumps(config, indent=4))
        file.close()
    except IOError as e:
        print(f"Failed to save config: {e}")
        return False
    
    return True

def init() -> None:
    load_config()
    testing.load_test_changes()
