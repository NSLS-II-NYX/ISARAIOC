import re
import json
import glob
import os
import textwrap
import time
import numpy

from datetime import datetime
from Queue import Queue
from threading import Thread

from enum import Enum
from softdev import epics, models, log
from twisted.internet import reactor

from . import isara, msgs

PUCK_LIST = [
    '1A', '2A', '3A', '4A', '5A',
    '1B', '2B', '3B', '4B', '5B', '6B',
    '1C', '2C', '3C', '4C', '5C',
    '1D', '2D', '3D', '4D', '5D', '6D',
    '1E', '2E', '3E', '4E', '5E',
    '1F', '2F',
]

NUM_PUCKS = 29
NUM_PUCK_SAMPLES = 16
NUM_PLATES = 8
NUM_WELLS = 192
NUM_ROW_WELLS = 24
STATUS_TIME = 0.1

STATUS_PATT = re.compile('^(?P<context>\w+)\((?P<msg>.*?)\)?$')

logger = log.get_module_logger(__name__)


class ToolType(Enum):
    #ORG NONE, UNIPUCK, ROTATING, PLATE, LASER, DOUBLE = range(6)
    CHANGER, CRYOTONG, UNIPUCK, DOUBLE, MINISPINE, ROTATING, PLATE, NONE, LASER = range(9)

#ORG class PuckType(Enum):
#ORG     ACTOR, UNIPUCK = range(2)
class SampleType(Enum):
    SPINE, COPPERCAP = range(2)

#ADD
class DataMatrixScan(Enum):
    NOREAD, READ = range(2)

#ADD
class Jaw(Enum):
    A, B = range(2)

StatusType = msgs.StatusType

class OffOn(Enum):
    OFF, ON = range(2)

class GoodBad(Enum):
    BAD, GOOD = range(2)

class OpenClosed(Enum):
    CLOSED, OPEN = range(2)

class CryoLevel(Enum):
    UNKNOWN, TOO_LOW, NORMAL, LOW, HIGH, TOO_HIGH = range(6)

class Position(Enum):
    HOME, SOAK, GONIO, DEWAR, UNKNOWN = range(5)

class ModeType(Enum):
    MANUAL, AUTO = range(2)

class ActiveType(Enum):
    INACTIVE, ACTIVE = range(2)

class EnableType(Enum):
    DISABLED, ENABLED = range(2)

class ErrorType(Enum):
    OK, WAITING, WARNING, ERROR = range(4)

class NormalError(Enum):
    NORMAL, ERROR = range(2)


class AuntISARA(models.Model):
    connected = models.Enum('CONNECTED', choices=ActiveType, default=0, desc="Robot Connection")
    enabled = models.Enum('ENABLED', choices=EnableType, default=1, desc="Robot Control")
    status = models.Enum('STATUS', choices=StatusType, desc="Robot Status")
    health = models.Enum('HEALTH', choices=ErrorType, desc="Robot Health")
    log = models.String('LOG', desc="Sample Operation Message", max_length=1024)
    warning = models.String('WARNING', max_length=1024, desc='Warning message')
    help = models.String('HELP', max_length=1024, desc='Help')
    message = models.String('MESSAGE', max_length=2048, desc='Message')

    # Inputs and Outputs
    input0_fbk = models.BinaryInput('STATE:INP0', desc='Digital Inputs 00-15')
    input1_fbk = models.BinaryInput('STATE:INP1', desc='Digital Inputs 16-31')
    input2_fbk = models.BinaryInput('STATE:INP2', desc='Digital Inputs 32-47')
    input3_fbk = models.BinaryInput('STATE:INP3', desc='Digital Inputs 48-63')

    emergency_ok = models.Enum('INP:emerg', choices=GoodBad, desc='Emergency/Air OK')
    collision_ok = models.Enum('INP:colSensor', choices=GoodBad, desc='Collision Sensor OK')
    cryo_level = models.Enum('INP:cryoLevel', choices=CryoLevel, desc='Cryo Level')
    gonio_ready = models.Enum('INP:gonioRdy', choices=OffOn, desc='Gonio Ready')
    sample_detected = models.Enum('INP:smplOnGonio', choices=OffOn, desc='Sample on Gonio')
    cryojet_fbk = models.Enum('INP:cryojet', choices=OffOn, desc='Cryojet Back')
    heartbeat = models.Enum('INP:heartbeat', choices=OffOn, desc='Heart beat')

    output0_fbk = models.BinaryInput('STATE:OUT0', desc='Digital Outpus 00-15')
    output1_fbk = models.BinaryInput('STATE:OUT1', desc='Digital Oututs 16-31')
    output2_fbk = models.BinaryInput('STATE:OUT2', desc='Digital Oututs 32-47')
    output3_fbk = models.BinaryInput('STATE:OUT3', desc='Digital Oututs 48-63')

    # Status
    mode_fbk = models.Enum('STATE:mode', choices=ModeType, desc='Control Mode')
    error_fbk = models.Integer('STATE:error', desc='Error Code')
    position_fbk = models.String('STATE:pos', max_length=40, desc='Position')
    fault_fbk = models.Enum('STATE:fault', choices=NormalError, desc='Fault Status')
    tool_fbk = models.Enum('STATE:tool', choices=ToolType, desc='Tool Status')
    tool_open_fbk = models.Enum('STATE:toolOpen', choices=OpenClosed, desc='Tool A Open')
    #ADD
    toolb_open_fbk = models.Enum('STATE:toolbOpen', choices=OpenClosed, desc='Tool B Open')
    path_fbk = models.String('STATE:path', max_length=40, desc='Path Name')
    puck_tool_fbk = models.Integer('STATE:toolPuck', min_val=0, max_val=29, desc='Puck On tool')
    puck_toolb_fbk = models.Integer('STATE:toolbPuck', min_val=0, max_val=29, desc='Puck On toolb')
    puck_diff_fbk = models.Integer('STATE:diffPuck', min_val=0, max_val=29, desc='Puck On Diff')
    sample_tool_fbk = models.Integer('STATE:toolSmpl', min_val=0, max_val=NUM_PUCK_SAMPLES, desc='On tool Sample')
    sample_toolb_fbk = models.Integer('STATE:toolbSmpl', min_val=0, max_val=NUM_PUCK_SAMPLES, desc='On toolb Sample')
    sample_diff_fbk = models.Integer('STATE:diffSmpl', min_val=0, max_val=NUM_PUCK_SAMPLES, desc='On Diff Sample')
    plate_fbk = models.Integer('STATE:plate', min_val=0, max_val=NUM_PLATES, desc='Plate Status')
    barcode_fbk = models.String('STATE:barcode', max_length=40, desc='Barcode Status')
    power_fbk = models.Enum('STATE:power', choices=OffOn, desc='Robot Power')
    running_fbk = models.Enum('STATE:running', choices=OffOn, desc='Path Running')
    #ADD DRY
    drying_fbk = models.Integer('STATE:drying', min_val=0, max_val=2, desc='Auto Drying')
    trajectory_fbk = models.Enum('STATE:traj', choices=OffOn, desc='Traj Running')
    autofill_fbk = models.Enum('STATE:autofill', choices=OffOn, desc='Auto-Fill')
    approach_fbk = models.Enum('STATE:approach', choices=OffOn, desc='Approaching')
    magnet_fbk = models.Enum('STATE:magnet', choices=OffOn, desc='Magnet')
    heater_fbk = models.Enum('STATE:heater', choices=OffOn, desc='Heater')
    lid_fbk = models.Enum('STATE:lidOpen', choices=OpenClosed, desc='Lid')
    software_fbk = models.Enum('STATE:software', choices=OffOn, desc='Software')
    remote_speed_fbk = models.Enum('STATE:remSpeed', choices=OffOn, desc='Remote Speed')

    speed_fbk = models.Float('STATE:speed', min_val=0, max_val=100, prec=0, units='%', desc='Speed Ratio')
    pos_dew_fbk = models.String('STATE:posDewar', max_length=40, desc='Position in Dewar')
    soak_count_fbk = models.Integer('STATE:soakCount', desc='Soak Count')
    pucks_fbk = models.String('STATE:pucks', max_length=40, desc='Puck Detection')
    pucks_bit0 = models.BinaryInput('STATE:pucks:bit0', desc='Puck Detection')
    pucks_bit1= models.BinaryInput('STATE:pucks:bit1', desc='Puck Detection')
    xpos_fbk = models.Float('STATE:posX', prec=2, desc='X-Pos')
    ypos_fbk = models.Float('STATE:posY', prec=2, desc='Y-Pos')
    zpos_fbk = models.Float('STATE:posZ', prec=2, desc='Z-Pos')
    rxpos_fbk = models.Float('STATE:posRX', prec=2, desc='RX-Pos')
    rypos_fbk = models.Float('STATE:posRY', prec=2, desc='RY-Pos')
    rzpos_fbk = models.Float('STATE:posRZ', prec=2, desc='RZ-Pos')
    mounted_fbk = models.String('STATE:onDiff', max_length=40, desc='On Gonio')
    tooled_fbk = models.String('STATE:onTool', max_length=40, desc='On Tool')

    #ADD
    highln2_fbk = models.Float('STATE:setHighLN2', prec=2, desc='Set High LN2 (%)')
    lowln2_fbk = models.Float('STATE:setLowLN2', prec=2, desc='Set High LN2 (%)')
    currln2_fbk = models.Float('STATE:currLN2', prec=2, desc='Current LN2 (%)')

    # Params
    next_param = models.String('PAR:nextPort', max_length=40, default='', desc='Port')
    next_after_param = models.String('PAR:nextAfterPort', max_length=40, default='', desc='After Port')
    barcode_param = models.Enum('PAR:barcode', choices=OffOn, default=0, desc='Barcode')
    tool_param = models.Enum('PAR:tool', choices=ToolType, default=1, desc='Tool')
    puck_param = models.Integer('PAR:puck', min_val=0, max_val=NUM_PUCKS, default=0, desc='Puck')
    #ADD next_puck
    next_puck = models.Integer('PAR:nextPuck', min_val=0, max_val=NUM_PUCKS, default=0, desc='Next Puck')
    sample_param = models.Integer('PAR:smpl', min_val=0, max_val=NUM_PUCK_SAMPLES, default=0, desc='Sample')
    #ADD next_sample
    next_sample = models.Integer('PAR:nextSmpl', min_val=0, max_val=NUM_PUCK_SAMPLES, default=0, desc='Next Sample')
    plate_param = models.Integer('PAR:plate', min_val=0, max_val=NUM_PLATES, desc='Plate')
    #ORG type_param = models.Enum('PAR:puckType', choices=PuckType, default=PuckType.UNIPUCK.value, desc='Puck Type')
    sample_type = models.Enum('PAR:smplType', choices=SampleType, default=SampleType.SPINE.value, desc='Sample Type')
    #ADD next_sample_type
    next_sample_type = models.Enum('PAR:nextSmplType', choices=SampleType, default=SampleType.SPINE.value, desc='Next Sample Type')
    #ADD datamatrix_scan
    datamatrix_scan = models.Enum('PAR:dataMatScan', choices=DataMatrixScan, default=DataMatrixScan.NOREAD.value, desc='Data Matrix Scan')
    #ADD jaw_param
    jaw_param = models.Enum('PAR:jaw', choices=Jaw, default=Jaw.A.value, desc='Jaw')
    #ADD gripper state
    gripper_tool_fbk = models.Integer('STATE:gripperTool', min_val=0, max_val=29, desc='State On Gripper A')
    gripper_toolb_fbk = models.Integer('STATE:gripperToolb', min_val=0, max_val=29, desc='State On Gripper B')

    pos_name = models.String('PAR:posName', max_length=40, default='', desc='Position Name')
    pos_force = models.Enum('PAR:posForce', choices=OffOn, default=0, desc='Overwrite Position')
    pos_tolerance = models.Float('PAR:posTol', default=0.1, prec=2, desc='Position Tolerance')

    # General Commands
    power_cmd = models.Toggle('CMD:power', desc='Power')
    #ADD
    reboot_cmd = models.Toggle('CMD:reboot', desc='Reboot')
    panic_cmd = models.Toggle('CMD:panic', desc='Panic')
    abort_cmd = models.Toggle('CMD:abort', desc='Abort')
    pause_cmd = models.Toggle('CMD:pause', desc='Pause')
    reset_cmd = models.Toggle('CMD:reset', desc='Reset')
    restart_cmd = models.Toggle('CMD:restart', desc='Restart')
    clear_barcode_cmd = models.Toggle('CMD:clrBarcode', desc='Clear Barcode')
    lid_cmd = models.Enum('CMD:lid', choices=('Close Lid', 'Open Lid'), desc='Lid')
    tool_cmd = models.Enum('CMD:tool', choices=('Close', 'Open'), desc='ToolA')
    #CHJ
    toolb_cmd = models.Enum('CMD:toolb', choices=('Close', 'Open'), desc='ToolB')
    faster_cmd = models.Toggle('CMD:faster', desc='Speed Up')
    slower_cmd = models.Toggle('CMD:slower', desc='Speed Down')
    magnet_enable = models.Toggle('CMD:magnet', desc='Magnet')
    heater_enable = models.Toggle('CMD:heater', desc='Heater')
    speed_enable = models.Toggle('CMD:speed', desc='Remote Speed')
    approach_enable = models.Toggle('CMD:approach', desc='Approaching')
    running_enable = models.Toggle('CMD:running', desc='Path Running')
    autofill_enable = models.Toggle('CMD:autofill', desc='LN2 AutoFill')

    # Trajectory Commands
    home_cmd = models.Toggle('CMD:home', desc='Home')
    #ADD
    recover_cmd = models.Toggle('CMD:recover', desc='Recover')
    safe_cmd = models.Toggle('CMD:safe', desc='Safe')
    put_cmd = models.Toggle('CMD:put', desc='Put')
    get_cmd = models.Toggle('CMD:get', desc='Get')
    getput_cmd = models.Toggle('CMD:getPut', desc='Get Put')
    barcode_cmd = models.Toggle('CMD:barcode', desc='Barcode')
    back_cmd = models.Toggle('CMD:back', desc='Back')
    soak_cmd = models.Toggle('CMD:soak', desc='Soak')
    dry_cmd = models.Toggle('CMD:dry', desc='Dry')
    pick_cmd = models.Toggle('CMD:pick', desc='Pick')
    change_tool_cmd = models.Toggle('CMD:chgTool', desc='Change Tool')

    calib_cmd = models.Toggle('CMD:toolCal', desc='Tool Calib')
    teach_gonio_cmd = models.Toggle('CMD:teachGonio', desc='Teach Gonio')
    teach_puck_cmd = models.Toggle('CMD:teachPuck', desc='Teach Puck')
    #ADD
    teach_dewar_cmd = models.Toggle('CMD:teachDewar', desc='Teach Dewar')

    # Maintenance commands
    clear_cmd = models.Toggle('CMD:clear', desc='Clear')
    set_diff_cmd = models.Toggle('CMD:setDiffSmpl', desc='Set Diff')
    set_tool_cmd = models.Toggle('CMD:setToolSmpl', desc='Set Tool')
    set_toolb_cmd = models.Toggle('CMD:setToolbSmpl', desc='Set Toolb')
    reset_params = models.Toggle('CMD:resetParams', desc='Reset Parameters')
    reset_motion = models.Toggle('CMD:resetMotion', desc='Reset Motion')
    save_pos_cmd = models.Toggle('CMD:savePos', desc='Save Position')

    #ADD
    set_maxsoaktime = models.Integer('PAR:setMaxSoakTime', default=1, min_val=1, max_val=31536000, desc='Max Soak Time (sec)')
    set_maxsoaknb = models.Integer('PAR:setMaxSoakNB', default=6, min_val=1, max_val=464, desc='Max Soak Num')
    set_autocloselidtimer = models.Integer('PAR:setAutoCloseLidTimer', default=0, min_val=0, max_val=34560, desc='Auto Close Lid Timer (min)')
    set_autodrytimer = models.Integer('PAR:setAutoDryTimer', default=0, min_val=0, max_val=34560, desc='Auto Dry Timer (min)')
    set_highln2 = models.Integer('PAR:setHighLN2', default=80, min_val=0, max_val=100, desc='High LN2 (%)')
    set_lowln2 = models.Integer('PAR:setLowLN2', default=70, min_val=0, max_val=100, desc='Low LN2 (%)')

    # Simplified commands
    dismount_cmd = models.Toggle('CMD:dismount', desc='Dismount')
    mount_cmd = models.Toggle('CMD:mount', desc='Mount')


def port2args(port):
    # converts '1A16' to puck=1, sample=16, tool=2 for UNIPUCK where NUM_PUCK_SAMPLES = 16
    # converts 'P2' to plate=2, tool=3 for Plates
    if len(port) < 3: return {}
    args = {}
    if port.startswith('P'):
        args = {
            'tool': ToolType.PLATE.value,
            'plate': zero_int(port[1]),
            'mode': 'plate'
        }
    else:
        args = {
            #ORG 'tool': ToolType.UNIPUCK.value,
            'tool': ToolType.DOUBLE.value,
            'puck': PUCK_LIST.index(port[:2])+1,
            'sample': zero_int(port[2:]),
            'mode': 'puck'
        }
    return args


def pin2port(puck, sample):
    # converts puck=1, sample=16 to '1A16'
    if all((puck, sample)):
        return '{}{}'.format(PUCK_LIST[puck-1], sample)
    else:
        return ''


def plate2port(plate):
    # converts plate=1, to 'P1'
    if plate:
        return 'P{}'.format(plate, )
    else:
        return ''


def zero_int(text):
    try:
        return int(text)
    except ValueError:
        return 0

def minus_int(text):
    try:
        return int(text)
    except ValueError:
        return -1

def name_to_tool(text):
    return {
        #ORG 'simple': ToolType.UNIPUCK.value,
        #ORG 'flange': ToolType.NONE.value,
        'toolchanger': ToolType.CHANGER.value,
        'doublegripper': ToolType.DOUBLE.value,
        'lasertool': ToolType.LASER.value,
    }.get(text.lower(), 1)


class AuntISARAApp(object):
    def __init__(self, device_name, address, command_port=10000, status_port=1000, positions='positions'):
        self.app_directory = os.getcwd()
        self.ioc = AuntISARA(device_name, callbacks=self)
        self.inbox = Queue()
        self.outbox = Queue()
        self.send_on = False
        self.recv_on = False
        self.user_enabled = False
        self.ready = False
        self.standby_active = False
        self.dewar_pucks = set()
        self.command_client = isara.CommandFactory(self)
        self.status_client = isara.StatusFactory(self)
        self.pending_clients = {self.command_client.protocol.message_type, self.status_client.protocol.message_type}

        reactor.connectTCP(address, status_port, self.status_client)
        reactor.connectTCP(address, command_port, self.command_client)

        # status pvs and conversion types
        # maps status position to record, converter pairs
        # [parse and put on pv record]
        #  (0, 'IOC0000-000:STATE:power', '0')
        #  (1, 'IOC0000-000:STATE:mode', '0')
        #  (2, 'IOC0000-000:STATE:default', '0')
        #  (3, 'IOC0000-000:STATE:tool', 'DoubleGripper')
        #  (4, 'IOC0000-000:STATE:pos', 'SOAK')
        #  (5, 'IOC0000-000:STATE:path', '')
        #  (6, 'IOC0000-000:STATE:gripperTool', '0')
        #  (7, 'IOC0000-000:STATE:gripperToolb', '0')
        #  (8, 'IOC0000-000:STATE:toolPuck', '-1')
        #  (9, 'IOC0000-000:STATE:toolSmpl', '-1')
        #  (10, 'IOC0000-000:STATE:toolbPuck', '-1')
        #  (11, 'IOC0000-000:STATE:toolbSmpl', '-1')
        #  (12, 'IOC0000-000:STATE:diffPuck', '9')
        #  (13, 'IOC0000-000:STATE:diffSmpl', '11')
        #  (16, 'IOC0000-000:STATE:barcode', '')
        #  (17, 'IOC0000-000:STATE:running', '0')
        #  (19, 'IOC0000-000:STATE:speed', '100.0')
        #  (20, 'IOC0000-000:STATE:autofill', '1')
        #  (21, 'IOC0000-000:STATE:soakCount', '7')
        self.status_map = {
            0:  (self.ioc.power_fbk, int), #OK
            1:  (self.ioc.mode_fbk, int), #OK
            2:  (self.ioc.fault_fbk, int), #OK
            3:  (self.ioc.tool_fbk, name_to_tool), #OK
            4:  (self.ioc.position_fbk, str), #OK
            5:  (self.ioc.path_fbk, str), #OK
            6:  (self.ioc.gripper_tool_fbk, minus_int), #OK New
            7:  (self.ioc.gripper_toolb_fbk, minus_int), #OK New
            8:  (self.ioc.puck_tool_fbk, minus_int), #OK
            9:  (self.ioc.sample_tool_fbk, minus_int), #OK
            10: (self.ioc.puck_toolb_fbk, minus_int), #OK New
            11: (self.ioc.sample_toolb_fbk, minus_int), #OK New
            12: (self.ioc.puck_diff_fbk, minus_int), #OK
            13: (self.ioc.sample_diff_fbk, minus_int), #OK
            16: (self.ioc.barcode_fbk, str), #OK
            17: (self.ioc.running_fbk, int), #OK
            19: (self.ioc.speed_fbk, float), #OK
            20: (self.ioc.autofill_fbk, int), #OK
            21: (self.ioc.soak_count_fbk, int), #OK
            22: (self.ioc.currln2_fbk, float), #OK
            23: (self.ioc.highln2_fbk, float), #OK
            24: (self.ioc.lowln2_fbk, float), #OK
            # ADD DRY
            26: (self.ioc.drying_fbk, int), #OK
        }
        self.position_map = [
            self.ioc.xpos_fbk, self.ioc.ypos_fbk, self.ioc.zpos_fbk,
            self.ioc.rxpos_fbk, self.ioc.rypos_fbk, self.ioc.rzpos_fbk
        ]
        self.input_map = {
            2:  self.ioc.trajectory_fbk, #OK
            17: self.ioc.tool_open_fbk, #OK
            19: self.ioc.toolb_open_fbk, #OK New
        }
        self.rev_input_map = {
            4:  self.ioc.emergency_ok, #OK
            12: self.ioc.collision_ok, #OK
            24: self.ioc.sample_detected, #OK
        }
        self.output_map = {
            26: self.ioc.gonio_ready, #OK
            27: self.ioc.cryojet_fbk, #OK
            40: self.ioc.magnet_fbk, #OK
            41: self.ioc.approach_fbk, #OK
        }

        self.mounting = False
        self.aborted = False
        self.fault_active = False

        self.positions_name = positions
        self.positions = self.load_positions()
        self.status_received = None

    def load_positions(self):
        """
        Load most recent file if one exists. Returns a dictionary of named robot positions.
        """
        data_files = glob.glob(os.path.join(self.app_directory, '{}*.dat'.format(self.positions_name)))
        if not data_files:
            return {}
        else:
            data_files.sort(key=lambda x: -os.path.getmtime(x))
            latest = data_files[0]

            logger.info('Using Position File: {}'.format(latest))
            with open(latest, 'r') as fobj:
                positions = json.load(fobj)
            return positions

    def save_positions(self):
        """
        Save current positions to a file. If previous file was older than today, create a new one with todays's date
        as a suffix.
        """
        logger.debug('Saving positions ...')
        positions_file = '{}-{}.dat'.format(self.positions_name, datetime.today().strftime('%Y%m%d'))
        with open(os.path.join(self.app_directory, positions_file), 'w') as fobj:
            json.dump(self.positions, fobj, indent=2)

    def ready_for_commands(self):
        return self.ready and self.ioc.enabled.get() and self.ioc.connected.get()

    def sender(self):
        """
        Main method which sends commands to the robot from the outbox queue. New commands are placed in the queue
        to be sent through this method. This method is called within the sender thread.
        """
        self.send_on = True
        epics.threads_init()
        while self.send_on:
            command = self.outbox.get()
            logger.debug('< {}'.format(command))
            try:
                self.command_client.send_message(command)
            except Exception as e:
                logger.error('{}: {}'.format(command, e))
            time.sleep(0)

    def receiver(self):
        """
        Main method which receives messages from the robot from the inbox queue. Messages from the robot are placed in
        the queue to be processed by this method. It is called within the receiver thread.
        """

        self.recv_on = True
        epics.threads_init()
        while self.recv_on:
            message, message_type = self.inbox.get()
            if message_type == isara.MessageType.RESPONSE:
                self.ioc.warning.put('')  # clear warning if command is successful
                logger.debug('> {}'.format(message))
            try:
                self.process_message(message, message_type)
            except Exception as e:
                logger.error('{}: {}'.format(message, e))
            time.sleep(0)

    def status_monitor(self):
        """
        Main monitor method which sends monior commands to the robot.
        """

        epics.threads_init()
        self.recv_on = True
        cmd_index = 0
        #ORG commands = ['state', 'di', 'di2', 'do', 'position', 'message']
        commands = ['state', 'di', 'do', 'position', 'message']
        while self.recv_on:
            self.status_received = None
            cmd = commands[cmd_index]
            self.status_client.send_message(cmd)
            cmd_index = (cmd_index + 1) % len(commands)
            timeout = 10 * STATUS_TIME
            while self.status_received != cmd and timeout > 0:
                time.sleep(STATUS_TIME)
                timeout -= STATUS_TIME

    def disconnect(self, client_type):
        self.pending_clients.add(client_type)
        self.recv_on = False
        self.send_on = False
        self.ioc.connected.put(0)

    def connect(self, client_type):
        self.pending_clients.remove(client_type)

        # all clients connected
        if not self.pending_clients:
            self.inbox.queue.clear()
            self.outbox.queue.clear()
            send_thread = Thread(target=self.sender)
            recv_thread = Thread(target=self.receiver)
            status_thread = Thread(target=self.status_monitor)
            send_thread.setDaemon(True)
            recv_thread.setDaemon(True)
            status_thread.setDaemon(True)
            send_thread.start()
            recv_thread.start()
            status_thread.start()
            self.ready = True
            self.ioc.connected.put(1)
            logger.warn('Controller ready!')
        else:
            self.ready = False

    def shutdown(self):
        logger.warn('Shutting down ...')
        self.recv_on = False
        self.send_on = False
        self.ioc.shutdown()

    def wait_for_position(self, *positions):
        timeout = 30
        while timeout > 0 and self.ioc.position_fbk.get() not in positions:
            timeout -= 0.01
            time.sleep(0.01)
        if timeout > 0:
            return True
        else:
            logger.warn('Timeout waiting for positions "{}"'.format(states))
            return False

    def wait_for_state(self, *states):
        timeout = 30
        state_values = [s.value for s in states]
        while timeout > 0 and self.ioc.status.get() not in state_values:
            timeout -= 0.01
            time.sleep(0.01)
        if timeout > 0:
            return True
        else:
            logger.warn('Timeout waiting for states "{}"'.format(states))
            return False

    def wait_in_state(self, state):
        timeout = 30
        while timeout > 0 and self.ioc.status.get() == state.value:
            timeout -= 0.01
            time.sleep(0.01)
        if timeout > 0:
            return True
        else:
            logger.warn('Timeout in state "{}"'.format(state))
            return False

    @staticmethod
    #ORG def make_args(tool=0, puck=0, sample=0, puck_type=PuckType.UNIPUCK.value, x_off=0, y_off=0, z_off=0, **kwargs):
    #ORG     return (tool, puck, sample) + (0,) * 4 + (puck_type, 0, 0) + (x_off, y_off, z_off)
    def make_args(tool=0, puck=0, sample=0, datamatrix_scan=0, next_puck=0, next_sample=0, sample_type=SampleType.SPINE.value, next_sample_type=SampleType.SPINE.value, x_off=0, y_off=0, z_off=0, **kwargs):
        return (tool, puck, sample) + (datamatrix_scan,) + (next_puck, next_sample) + (sample_type, next_sample_type, 0, 0) + (x_off, y_off, z_off)

    def send_command(self, command, *args):
        self.standby_active = False
        if self.ready_for_commands():
            if args:
                cmd = '{}({})'.format(command, ','.join([str(arg) for arg in args]))
            else:
                cmd = command
            self.outbox.put(cmd)

    def send_traj_command(self, command, *args):
        self.standby_active = False
        if self.ready_for_commands():
            if args:
                #ORG cmd = '{}({})'.format(command, ','.join([str(arg) for arg in args]))
                cmd = 'traj({},{})'.format(command, ','.join([str(arg) for arg in args]))
            else:
                cmd = command
            self.outbox.put(cmd)

    def receive_message(self, message, message_type):
        self.inbox.put((message, message_type))

    def process_message(self, message, message_type):
        if message_type == isara.MessageType.STATUS:
            # process state messages
            self.parse_status(message)
        else:
            # process response messages
            self.ioc.log.put(message)

    def parse_inputs(self, bitstring):
        inputs = [self.ioc.input0_fbk, self.ioc.input1_fbk, self.ioc.input2_fbk, self.ioc.input3_fbk]

        for pv, bits in zip(inputs, textwrap.wrap(bitstring, 16)):
            pv.put(int(bits, 2))
        for i, bit in enumerate(bitstring):
            if i in self.input_map:
                self.input_map[i].put(int(bit))
            if i in self.rev_input_map:
                self.rev_input_map[i].put((int(bit) + 1) % 2)

        #REM logger.info('parse_inputs: bitstring={}'.format(map(int, bitstring[3:7])))

        # setup LN2 status & alarms
        hihi, hi, lo, lolo = map(int, bitstring[3:7])
        if not hihi:
            self.ioc.cryo_level.put(CryoLevel.TOO_HIGH.value)
        elif not lolo:
            self.ioc.cryo_level.put(CryoLevel.TOO_LOW.value)
        elif hi:
            self.ioc.cryo_level.put(CryoLevel.HIGH.value)
        elif lo:
            self.ioc.cryo_level.put(CryoLevel.LOW.value)
        else:
            self.ioc.cryo_level.put(CryoLevel.NORMAL.value)

    def parse_outputs(self, bitstring):
        outputs = [self.ioc.output0_fbk, self.ioc.output1_fbk, self.ioc.output2_fbk, self.ioc.output3_fbk]

        for pv, bits in zip(outputs, textwrap.wrap(bitstring, 16)):
            pv.put(int(bits, 2))
        for i, bit in enumerate(bitstring):
            if i in self.output_map:
                pv = self.output_map[i]
                pv.put(int(bit))

    def calc_position(self):
        self.standby_active = False
        cur = numpy.array([
            self.ioc.xpos_fbk.get(), self.ioc.ypos_fbk.get(), self.ioc.zpos_fbk.get(),
        ])
        found = False
        name = ""
        for name, info in self.positions.items():
            pos = numpy.array([
                info['x'], info['y'], info['z'],
            ])
            dist = numpy.linalg.norm(cur-pos)
            if dist <= info['tol']:
                found = True
                if self.ioc.position_fbk.get() != name:
                    self.ioc.position_fbk.put(name)
                    # Set the standby flag whenever the robot goes to the DRY position
                    # flag stays active until the next command is sent
                    if 'DRY' in name:
                        self.standby_active = True
                continue
        if not found:
            #ORG self.ioc.position_fbk.put('UNKNOWN')
            self.ioc.position_fbk.put('Undefined')
           

    def require_position(self, *allowed):
        if not self.positions.keys():
            self.warn('No positions have been defined')
            self.ioc.help.put('Please move the robot manually and save positions named `{}`'.format(' | '.join(allowed)))
            return False

        current = self.ioc.position_fbk.get()
        for pos in allowed:
            if re.match('^' + pos + '(?:_\w*)?$', current):
                return True
        self.warn('Command allowed only from ` {} ` position'.format(' | '.join(allowed)))
        self.ioc.help.put('Please move the robot into the correct position and the re-issue the command')

    def require_tool(self, *tools):
        if self.ioc.tool_fbk.get() in [t.value for t in tools]:
            return True
        else:
            self.warn('Invalid tool for command!')

    def warn(self, msg):
        self.ioc.warning.put('{} {}'.format(datetime.now().strftime('%b/%d %H:%M:%S'), msg))

    def parse_status(self, message):
        patt = re.compile('^(?P<context>\w+)\((?P<msg>.*?)\)?$')
        m = patt.match(message)
        next_status = None
        cur_status = self.ioc.status.get()
        if m:
            details = m.groupdict()
            #ADD
            msg_size = details['msg'].index(')')
            self.status_received = details['context']
            if details['context'] == 'state':
                my_msg = 'mydebug> {}:{}'.format(datetime.today().strftime('%Y%m%d'), details['msg'][0:msg_size-1])
                print( my_msg )
                for i, value in enumerate(details['msg'][0:msg_size-1].split(',')):
                    #REM logger.info('parse_status: i= {}, value= {}'.format(i, value))
                    if i not in self.status_map: continue
                    record, converter = self.status_map[i]
                    try:
                        record.put(converter(value))
                    except ValueError:
                        logger.warning('Unable to parse state: {}'.format(message))

                #REM logger.info('parse_status: matched fault_active= {}'.format(self.fault_active))

                # determine robot state
                if self.fault_active:
                    next_status = StatusType.FAULT.value
                elif self.ioc.running_fbk.get() and self.standby_active:
                    next_status = StatusType.STANDBY.value
                elif self.ioc.running_fbk.get() and self.ioc.trajectory_fbk.get():
                    next_status = StatusType.BUSY.value
                elif not self.ioc.running_fbk.get():
                    next_status = StatusType.IDLE.value
                #CHJ
                if self.ioc.drying_fbk.get():
                    next_status = StatusType.DRYING.value
                #CHJ
                self.fault_active = False

            elif details['context'] == 'position':
                for i, value in enumerate(details['msg'][0:msg_size-1].split(',')):
                    try:
                        self.position_map[i].put(float(value))
                    except ValueError:
                        logger.warning('Unable to parse position: {}'.format(message))
                self.calc_position()
            #REM elif details['context'] == 'di2':
            #REM     # puck detection
            #REM     bitstring = details['msg'].replace(',', '')
            #REM     self.ioc.pucks_fbk.put(bitstring)
            #REM     bit0, bit1 = textwrap.wrap(bitstring, 16)
            #REM     self.ioc.pucks_bit0.put(int(bit0[::-1], 2))
            #REM     self.ioc.pucks_bit1.put(int(bit1[::-1], 2))
            # 56 - 84
            # 56:71 (16)
            # 72:84 (13)
            elif details['context'] == 'di':
                # process inputs
                bitstring = details['msg'][0:msg_size-1].replace(',', '').ljust(64, '0')
                self.parse_inputs(bitstring)
            elif details['context'] == 'do':
                # process outputs
                bitstring = details['msg'][0:msg_size-1].replace(',', '').ljust(64, '0')
                self.parse_outputs(bitstring)
                # CHJ
                #ORG bitstring = bitstring[56:85]
                bitstring = '11111111111111111111111111111'
                bitstring = bitstring[0:29]
                self.ioc.pucks_fbk.put(bitstring)
                bit0, bit1 = textwrap.wrap(bitstring, 16)
                self.ioc.pucks_bit0.put(int(bit0[::-1], 2))
                self.ioc.pucks_bit1.put(int(bit1[::-1], 2))
            elif details['context'] == 'message':
                self.ioc.log.put(details['msg'][0:msg_size-1])
        else:
            # must be messages
            self.status_received = 'message'
            if message.strip():
                warning, help, state, bit = msgs.parse_error(message.strip())
                bitarray = list(bin(self.ioc.error_fbk.get())[2:].rjust(32, '0'))
                if bit is not None:
                    bitarray[bit] = '1'
                    new_value = int(''.join(bitarray), 2)
                    if new_value != self.ioc.error_fbk.get():
                        self.ioc.error_fbk.put(new_value)
                    if state == StatusType.FAULT:
                        self.ioc.health.put(ErrorType.ERROR.value)
                        self.fault_active = True

                        #REM logger.info('parse_status: no matched fault_active= {}'.format(self.fault_active))
                else:
                    self.ioc.error_fbk.put(0)
            else:
                self.ioc.health.put(ErrorType.OK.value)
                self.ioc.error_fbk.put(0)
                self.fault_active = False

                #REM logger.info('parse_status: no matched fault_active= {}'.format(self.fault_active))

            msg_idx = message.strip().index('\0')
            old_message = self.ioc.message.get() 
            new_message = message.strip()[0:msg_idx]
            if new_message != old_message:
                self.ioc.message.put(new_message)

        if next_status is not None and next_status != cur_status:
            self.ioc.status.put(next_status)

    # def mount_operation(self, cmd, args):
    #     epics.threads_init()
    #     allowed_tools = (ToolType.UNIPUCK, ToolType.ROTATING, ToolType.DOUBLE, ToolType.PLATE)
    #     puck_tools = (ToolType.UNIPUCK.value, ToolType.ROTATING.value, ToolType.DOUBLE.value)
    #     if not self.mounting:
    #         self.mounting = True
    #         self.aborted = False
    #
    #         port = self.ioc.next_param.get().strip()
    #         current = self.ioc.mounted_fbk.get().strip()
    #         params = port2args(port)
    #
    #         if not (params and all(params.values())):
    #             self.warn('Invalid Port for mounting: {}'.format(port))
    #             self.mounting = False
    #             return
    #
    #         if params.get('tool') in puck_tools:
    #             if self.ioc.barcode_param.get():
    #                 command = 'put_bcrd' if not current else 'getput_bcrd'
    #             else:
    #                 command = 'put' if not current else 'getput'
    #         else:
    #             command = 'putplate' if not current else 'getputplate'
    #
    #         current_tool = self.ioc.tool_fbk.get()
    #         if self.require_position('SOAK') and self.require_tool(*allowed_tools):
    #             if params['tool'] == current_tool and current_tool in puck_tools:
    #                 args = self.make_args(
    #                     tool=params['tool'], puck=params['puck'], sample=params['sample'],
    #                     puck_type=params['tool']
    #                 )
    #             else:
    #                 args = (
    #                     ToolType.PLATE.value, 0, 0, 0, 0, ioc.plate_param.get()
    #                 )
    #             self.send_command(command, *args)
    #
    #         self.mounting = False

    # callbacks
    def do_mount_cmd(self, pv, value, ioc):
        #TEST
        self.mounting = False
        if value and self.require_position('SOAK') and not self.mounting:
            self.standby_active = False
            self.mounting = True
            port = ioc.next_param.get().strip()
            #ADD
            next_port = ioc.next_after_param.get().strip()
            current = ioc.mounted_fbk.get().strip()
            command = 'put' if not current else 'getput'
            params = port2args(port)
            #ADD
            next_params = port2args(next_port)
            if params and all(params.values()):
                if params['mode'] == 'puck':
                    ioc.tool_param.put(params['tool'])
                    ioc.puck_param.put(params['puck'])
                    ioc.sample_param.put(params['sample'])
                    #ADD
                    #ioc.next_puck.put(next_params['puck'])
                    #ioc.next_sample.put(next_params['sample'])
                elif params['mode'] == 'plate':
                    ioc.tool_param.put(params['tool'])
                    ioc.plate_param.put(params['plate'])
                    #ADD
                    #ioc.next_puck.put(next_params['puck'])
                    #ioc.next_sample.put(next_params['sample'])
                else:
                    self.warn('Invalid Port parameters for mounting: {}'.format(params))
                    self.mounting = False
                    return

                if command == 'put':
                    self.ioc.put_cmd.put(1)
                elif command == 'getput':
                    self.ioc.getput_cmd.put(1)
            else:
                self.warn('Invalid Port for mounting: {}'.format(port))
                self.mounting = False

    def do_dismount_cmd(self, pv, value, ioc):
        if value and self.require_position('SOAK') and not self.mounting:
            self.mounting = True
            self.standby_active = False
            current = ioc.mounted_fbk.get().strip()
            params = port2args(current)
            if params and all(params.values()):
                ioc.tool_param.put(params['tool'])
                self.ioc.get_cmd.put(1)
            else:
                self.warn('Invalid port or sample not mounted')
                self.mounting = False

    def do_power_cmd(self, pv, value, ioc):
        if value:
            cmd = 'off' if ioc.power_fbk.get() else 'on'
            self.send_command(cmd)

    #ADD
    def do_reboot_cmd(self, pv, value, ioc):
        if value:
            cmd = 'resetprogram'
            self.send_command(cmd)

    def do_panic_cmd(self, pv, value, ioc):
        if value:
            self.send_command('panic')

    def do_abort_cmd(self, pv, value, ioc):
        if value:
            self.send_command('abort')
            self.aborted = True
            self.mounting = False

    def do_pause_cmd(self, pv, value, ioc):
        if value:
            self.send_command('pause')

    def do_reset_cmd(self, pv, value, ioc):
        if value:
            self.send_command('reset')
            self.ioc.error_fbk.put(0)
            self.ioc.help.put('')
            self.ioc.warning.put('')
            self.mounting = False

    def do_restart_cmd(self, pv, value, ioc):
        if value:
            self.send_command('restart')

    def do_clear_barcode_cmd(self, pv, value, ioc):
        if value:
            self.send_command('clearbcrd')

    def do_lid_cmd(self, pv, value, ioc):
        if value:
            self.send_command('openlid')
        else:
            self.send_command('closelid')

    def do_tool_cmd(self, pv, value, ioc):
        if value:
            self.send_command('opentool')
        else:
            self.send_command('closetool')

    def do_toolb_cmd(self, pv, value, ioc):
        if value:
            self.send_command('opentoolb')
        else:
            self.send_command('closetoolb')

    def do_faster_cmd(self, pv, value, ioc):
        if value:
            self.send_command('speedup')

    def do_slower_cmd(self, pv, value, ioc):
        if value:
            self.send_command('speeddown')

    def do_magnet_enable(self, pv, value, ioc):
        if value:
            cmd = 'magnetoff' if ioc.magnet_fbk.get() else 'magneton'
            self.send_command(cmd)

    def do_heater_enable(self, pv, value, ioc):
        if value:
            cmd = 'heateroff' if ioc.heater_fbk.get() else 'heateron'
            self.send_command(cmd)

    def do_speed_enable(self, pv, value, ioc):
        if value:
            st, cmd = (0, 'remotespeedoff') if ioc.remote_speed_fbk.get() else (1, 'remotespeedon')
            self.send_command(cmd)
            ioc.remote_speed_fbk.put(st)

    def do_approach_enable(self, pv, value, ioc):
        if value:
            cmd = 'cryoOFF' if ioc.approach_fbk.get() else 'cryoON'
            self.send_command(cmd, ioc.tool_fbk.get())

    def do_running_enable(self, pv, value, ioc):
        if value:
            cmd = 'trajOFF' if ioc.running_fbk.get() else 'trajON'
            self.send_command(cmd, ioc.tool_fbk.get())

    def do_autofill_enable(self, pv, value, ioc):
        if value:
            cmd = 'reguloff' if ioc.autofill_fbk.get() else 'regulon'
            self.send_command(cmd)

    def do_home_cmd(self, pv, value, ioc):
        if value and self.require_position('SOAK', 'HOME', 'Undefined'):
            #ORG self.send_command('home', ioc.tool_fbk.get())
            self.send_traj_command('home', ioc.tool_fbk.get())

    #ADD
    def do_recover_cmd(self, pv, value, ioc):
        self.send_traj_command('recover', ioc.tool_fbk.get())

    def do_change_tool_cmd(self, pv, value, ioc):
        if value and self.require_position('HOME'):
            if ioc.tool_param.get() != ioc.tool_fbk.get():
                #ORG self.send_command('home', ioc.tool_fbk.get())
                self.send_traj_command('changetool', ioc.tool_param.get())
            else:
                self.warn('Requested tool already present, command ignored')

    def do_safe_cmd(self, pv, value, ioc):
        if value:
            self.send_command('safe', ioc.tool_fbk.get())

    def do_put_cmd(self, pv, value, ioc):
        allowed_tools = (ToolType.UNIPUCK, ToolType.ROTATING, ToolType.DOUBLE, ToolType.PLATE)
        if value and self.require_position('SOAK') and self.require_tool(*allowed_tools):
            if self.ioc.tool_fbk.get() in [ToolType.UNIPUCK.value, ToolType.ROTATING.value, ToolType.DOUBLE.value]:
                args = self.make_args(
                    tool=ioc.tool_param.get(), puck=ioc.puck_param.get(), sample=ioc.sample_param.get(),
                    datamatrix_scan=ioc.datamatrix_scan.get(),
                    #ADD
                    next_puck=ioc.next_puck.get(), next_sample=ioc.next_sample.get(),
                    #ORG puck_type=ioc.type_param.get()
                    sample_type=ioc.sample_type.get(), next_sample_type=ioc.next_sample_type.get()
                )
                #ORG cmd = 'put_bcrd' if ioc.barcode_param.get() else 'put'
                cmd = 'put'
            else:
                args = (
                    #ORG ToolType.PLATE.value, 0, 0, 0, 0, ioc.plate_param.get()
                    ioc.tool_param.get(), ioc.plate_param.get()
                )
                #ORG cmd = 'putplate'
                cmd = 'putplate'
            #ORG self.send_command(cmd, *args)
            self.send_traj_command(cmd, *args)

    def do_get_cmd(self, pv, value, ioc):
        allowed_tools = (ToolType.UNIPUCK, ToolType.ROTATING, ToolType.DOUBLE, ToolType.PLATE)
        if value and self.require_position('SOAK') and self.require_tool(*allowed_tools):
            if self.ioc.tool_fbk.get() in [ToolType.UNIPUCK.value, ToolType.ROTATING.value, ToolType.DOUBLE.value]:
                #ADD
                args = self.make_args(
                    tool=ioc.tool_param.get(), puck=0, sample=0,
                    datamatrix_scan=ioc.datamatrix_scan.get(),
                    #ADD
                    next_puck=0, next_sample=0,
                    #ORG puck_type=ioc.type_param.get()
                    sample_type=0, next_sample_type=0
                )
                #ORG cmd = 'get'
                cmd = 'get'
            else:
                #ADD
                args = (
                    ioc.tool_param.get(),
                )
                #ORG cmd = 'getplate'
                cmd = 'getplate'
            #ORG self.send_command(cmd, ioc.tool_param.get())
            self.send_traj_command(cmd, *args)

    def do_getput_cmd(self, pv, value, ioc):
        allowed_tools = (ToolType.UNIPUCK, ToolType.ROTATING, ToolType.DOUBLE, ToolType.PLATE)
        if value and self.require_position('SOAK') and self.require_tool(*allowed_tools):

            if self.ioc.tool_fbk.get() in [ToolType.UNIPUCK.value, ToolType.ROTATING.value, ToolType.DOUBLE.value]:
                #ORG cmd = 'getput_bcrd' if ioc.barcode_param.get() else 'getput'
                cmd = 'getput'
                args = self.make_args(
                    tool=ioc.tool_param.get(), puck=ioc.puck_param.get(), sample=ioc.sample_param.get(),
                    datamatrix_scan=ioc.datamatrix_scan.get(),
                    #ADD
                    next_puck=ioc.next_puck.get(), next_sample=ioc.next_sample.get(),
                    #ORG puck_type=ioc.type_param.get()
                    sample_type=ioc.sample_type.get(), next_sample_type=ioc.next_sample_type.get()
                )
            else:
                #ADD
                args = (
                    ioc.tool_param.get(),
                )
                #ORG cmd = 'getplate'
                cmd = 'getplate'
            #ORG self.send_command(cmd, *args)
            self.send_traj_command(cmd, *args)

    def do_barcode_cmd(self, pv, value, ioc):
        if value and self.require_position('SOAK'):
            args = (
                ioc.tool_param.get(), ioc.puck_param.get(), ioc.sample_param.get(),
                0, 0, 0, ioc.sample_type.get()
            )
            cmd = 'datamatrix'
            #ORG self.send_command('barcode', *args)
            self.send_traj_command(cmd, *args)

    def do_back_cmd(self, pv, value, ioc):
        if value and self.require_position('SOAK'):
            if ioc.tooled_fbk.get():
                #ORG self.send_command('back', ioc.tool_fbk.get())
                self.send_traj_command('back', ioc.tool_fbk.get())
            else:
                self.warn('No sample on tool, command ignored')

    def do_soak_cmd(self, pv, value, ioc):
        allowed = (ToolType.DOUBLE, ToolType.UNIPUCK, ToolType.ROTATING)
        if value and self.require_position('HOME') and self.require_tool(*allowed):
            #ORG self.send_command('soak', ioc.tool_fbk.get())
            self.send_traj_command('soak', ioc.tool_fbk.get())

    def do_dry_cmd(self, pv, value, ioc):
        allowed = (ToolType.DOUBLE, ToolType.UNIPUCK, ToolType.ROTATING)
        if value and self.require_position('SOAK', 'HOME') and self.require_tool(*allowed):
            #ORG self.send_command('dry', ioc.tool_fbk.get())
            self.send_traj_command('dry', ioc.tool_fbk.get())

    def do_pick_cmd(self, pv, value, ioc):
        if value and self.require_tool(ToolType.DOUBLE):
            args = (
                ioc.tool_param.get(), ioc.puck_param.get(), ioc.sample_param.get(),
                ioc.datamatrix_scan.get(), 0, 0, ioc.sample_type.get()
            )
            #ORG self.send_command('pick', *args)
            self.send_traj_command('pick', *args)

    def do_calib_cmd(self, pv, value, ioc):
        if value and self.require_position('HOME') and (self.require_tool(ToolType.LASER) or self.require_tool(ToolType.DOUBLE)):
            #ORG self.send_command('toolcal', ioc.tool_fbk.get())
            self.send_traj_command('toolcal', ioc.tool_fbk.get())

    def do_teach_gonio_cmd(self, pv, value, ioc):
        if value and self.require_position('HOME') and self.require_tool(ToolType.LASER):
            #ORG self.send_command('teach_gonio', ToolType.LASER.value)
            self.send_traj_command('teachgonio', ToolType.LASER.value)

    def do_teach_puck_cmd(self, pv, value, ioc):
        if value and self.require_tool(ToolType.LASER) and self.require_position('HOME'):
            if ioc.puck_param.get():
                #ORG self.send_command('teach_puck', ToolType.LASER.value, ioc.puck_param.get())
                self.send_traj_command('teachpuck', ToolType.LASER.value, ioc.puck_param.get())
            else:
                self.warn('Please select a puck number')

    #ADD
    def do_teach_dewar_cmd(self, pv, value, ioc):
        if value and self.require_tool(ToolType.LASER) and self.require_position('HOME'):
            #ORG self.send_traj_command('teachdewar', ToolType.LASER.value)
            self.send_traj_command('teachdewar', ToolType.LASER.value, ioc.puck_param.get())

    def do_set_diff_cmd(self, pv, value, ioc):
        if value:
            current = ioc.next_param.get()
            if current.strip():
                params = port2args(current)
                #ORG self.send_command('settool', params['puck'], params['sample'], ioc.puck_param.get())
                self.send_command('setdiffr', params['puck'], params['sample'], ioc.sample_type.get())
            else:
                self.warn('No Sample specified')

    def do_set_tool_cmd(self, pv, value, ioc):
        if value:
            current = ioc.next_param.get()
            if current.strip() and self.require_tool(ToolType.DOUBLE):
                params = port2args(current)
                #ORG self.send_command('settool', params['puck'], params['sample'], ioc.puck_param.get())
                self.send_command('settool', params['puck'], params['sample'], ioc.sample_type.get(), ioc.jaw_param.get())
            else:
                self.warn('No Sample specified')

    def do_set_toolb_cmd(self, pv, value, ioc):
        if value and self.require_tool(ToolType.DOUBLE):
            current = ioc.next_param.get()
            if current.strip():
                params = port2args(current)
                self.send_command('settool2', params['puck'], params['sample'], ioc.sample_type.get())
            else:
                self.warn('No Sample specified')

    #ADD
    def do_set_maxsoaktime(self, pv, value, ioc):
        if value:
            self.send_command('setmaxsoaktime', value)
    def do_set_maxsoaknb(self, pv, value, ioc):
        if value:
            self.send_command('setmaxsoaknb', value)
    def do_set_autocloselidtimer(self, pv, value, ioc):
        if value:
            self.send_command('setautocloselidtimer', value)
    def do_set_autodrytimer(self, pv, value, ioc):
        if value:
            self.send_command('setautodrytimer', value)
    def do_set_highln2(self, pv, value, ioc):
        if value:
            self.send_command('sethighln2', value)
    def do_set_lowln2(self, pv, value, ioc):
        if value:
            self.send_command('setlowln2', value)

    def do_clear_cmd(self, pv, value, ioc):
        if value:
            #ORG self.send_command('clear memory')
            self.send_command('clearmemory')

    def do_reset_params(self, pv, value, ioc):
        if value:
            self.send_command('reset parameters')

    def do_reset_motion(self, pv, value, ioc):
        if value:
            self.send_command('resetMotion')

    def do_sample_diff_fbk(self, pv, value, ioc):
        port = pin2port(ioc.puck_diff_fbk.get(), value)
        ioc.mounted_fbk.put(port)
        ioc.next_param.put('')

    def do_plate_fbk(self, pv, value, ioc):
        if value:
            port = plate2port(value)
            ioc.tooled_fbk.put(port)

    def do_pucks_fbk(self, pv, value, ioc):
        if len(value) != NUM_PUCKS:
            logger.error('Puck Detection does not contain {} values!'.format(NUM_PUCKS))
        else:
            pucks_detected = {v[1] for v in zip(value, PUCK_LIST) if v[0] == '1'}
            added = pucks_detected - self.dewar_pucks
            removed = self.dewar_pucks - pucks_detected
            self.dewar_pucks = pucks_detected
            logger.info('Pucks changed: added={}, removed={}'.format(list(added), list(removed)))

            # If currently mounting a puck and it is removed abort
            on_tool = ioc.tooled_fbk.get().strip()
            if on_tool and on_tool[:2] in removed and ioc.status.get() in [StatusType.BUSY.value]:
                msg = 'Target puck removed while mounting. Aborting! Manual recovery required.'
                logger.error(msg)
                self.warn(msg)
                self.send_command('abort')

    def do_save_pos_cmd(self, pv, value, ioc):
        if value and ioc.pos_name.get().strip():
            pos_name = ioc.pos_name.get().strip().replace(' ', '_')
            tolerance = ioc.pos_tolerance.get()
            if ioc.pos_force.get() or pos_name not in self.positions:
                self.positions[pos_name] = {
                    'x': ioc.xpos_fbk.get(),
                    'y': ioc.ypos_fbk.get(),
                    'z': ioc.zpos_fbk.get(),
                    'rx': ioc.rxpos_fbk.get(),
                    'ry': ioc.rypos_fbk.get(),
                    'rz': ioc.rzpos_fbk.get(),
                    'tol': tolerance,
                }
                self.save_positions()
            ioc.pos_force.put(0)
            ioc.pos_name.put('')

    def do_sample_tool_fbk(self, pv, value, ioc):
        port = pin2port(ioc.puck_tool_fbk.get(), value)
        ioc.tooled_fbk.put(port)
    
    def do_status(self, pv, value, ioc):
        if value == 0:
            if ioc.error_fbk.get():
                ioc.reset_cmd.put(1)
            self.mounting = False

    def do_error_fbk(self, pv, value, ioc):
        if value:
            bitarray = list(bin(value)[2:].rjust(32, '0'))
            errors = filter(None, [msgs.MESSAGES.get(i) for i, bit in enumerate(bitarray) if bit == '1'])
            if errors:
                texts = [(err.get('description', ''), err.get('help')) for err in errors ]
                warnings, help = zip(*texts)
                warning_text = '; '.join(warnings)
                help_text = '; '.join(help)
                if warning_text:
                    self.warn(warning_text)
                if help_text:
                    ioc.help.put(help)
        else:
            ioc.help.put('')
