import re
from enum import Enum


class StatusType(Enum):
    #ORG IDLE, WAITING, BUSY, STANDBY, FAULT = range(5)
    IDLE, WAITING, BUSY, STANDBY, FAULT, DRYING = range(6)


MESSAGES = {
    0: {
        "error": "doors opened",
        "description": "Doors opened",
        "help": "Close the door or switch to Manual mode"
    },
    1: {
        "error": "Manual brake control selected",
        "description": "Manual brake button is not on the 0 position",
        "help": "Turn the manual brake dial to the 0 position",
        "state": StatusType.FAULT,
    },
    2: {
        "error": "emergency stop or air pressure fault",
        "description": "Emergency stop pressed or the compressed air pressure too low",
        "help": "Inspect the robot, eliminate the risk and turn-off the emergency stop or check air pressure",
        "state": StatusType.FAULT,
    },
    3: {
        "error": "collision detection",
        "description": "The robot collided with something",
        "help": ("Abort the current task; safely unlock the brakes and move the robot manually; "
                 "re-engage the shock detector and run the 'safe' command"),
        "state": StatusType.FAULT,
    },
    4: {
        "error": "Modbus communication fault",
        "description": "Internal communication fault",
        "help": ("Inspect the ethernet cable connections inside the electro-pneumatic rack, "
                 "and check the power of the CS8C controller and the PLC"),
        "state": StatusType.FAULT,
    },
    5: {
        "error": "LOC menu not disabled",
        "description": "The current menu on the teach pendant is 'LOC'",
        "help": "Quit the 'LOC' menu on the Teach Pendant",
        "state": StatusType.FAULT,
    },
    6: {
        "error": "Remote Mode requested",
        "description": "Remote mode is not selected",
        "help": "Switch to remote mode"
    },
    7: {
        "error": "Disabled when path is running",
        "description": "A command was sent while already processing a task",
        "help": "Wait for current task to complete"
    },
    8: {
        "error": "X- collision",
        "description": "X- limit reached",
        "help": "Modify the trajectory or adjust the limit",
        "state": StatusType.FAULT,
    },
    9: {
        "error": "X+ collision",
        "description": "X+ limit reached",
        "help": "Modify the trajectory or adjust the limit",
        "state": StatusType.FAULT,
    },
    10: {
        "error": "Y- collision",
        "description": "Y- limit reached",
        "help": "Modify the trajectory or adjust the limit",
        "state": StatusType.FAULT,
    },
    11: {
        "error": "Y+ collision",
        "description": "Y+ limit reached",
        "help": "Modify the trajectory or adjust the limit",
        "state": StatusType.FAULT,
    },
    12: {
        "error": "Z- collision",
        "description": "Z- limit reached",
        "help": "Modify the trajectory or adjust the limit",
        "state": StatusType.FAULT,
    },
    13: {
        "error": "Z+ collision",
        "description": "Z+ limit reached",
        "help": "Modify the trajectory or adjust the limit",
        "state": StatusType.FAULT,
    },
    14: {
        "error": "WAIT for RdTrsf condition",
        "description": "Waiting for endstation to be ready ...",
        "help": "Verify that endstation is going to mount mode",
        "state": StatusType.WAITING,
    },
    15: {
        "error": "WAIT for SplOn condition",
        "description": "Waiting for sample on gonio ...",
        "help": "Verify that sample on gonio detection is working properly",
        "state": StatusType.WAITING,
    },
    16: {
        "error": "low level alarm",
        "description": "LN2 level in the Dewar is too low",
        "help": "Check the LN2 supply",
    },
    17: {
        "error": "high level alarm",
        "description": "LN2 level in the Dewar is too high",
        "help": "Close the main valve of the LN2 supply"
    },
    18: {
        "error": "No LN2 available, regulation stopped",
        "description": "No LN2 available, autofill stopped",
        "help": "Check LN2 main supply, check phase sensor",
        "state": StatusType.FAULT,
    },
    19: {
        "error": "FillingUp Timeout",
        "description": "Maximum time for filling up was exceeded",
        "help": "Check LN2 main supply, check level sensor",
    },
    20: {
        "error": "collision at the gonio",
        "description": "Collision at gonio",
        "help": "Abort task and safely return robot home. If pin is in gripper, return it to puck using 'back' command.",
        "state":StatusType.FAULT,
    }
}


def parse_error(message):
    """
    Parse an error message into a warning text and a help text and error code bit

    :param message: Message from the status port, return value of the 'message' command
    :return: (description, help, bit) a tuple of strings
    """

    for bit, info in MESSAGES.items():
        if re.search(info['error'], message):
            return info['description'], info['help'], info.get('state'), bit

    return "", "", None, None
