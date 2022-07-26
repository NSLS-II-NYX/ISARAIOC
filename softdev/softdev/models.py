import collections
import multiprocessing
import os
import shutil
import subprocess
import time
from enum import EnumMeta

from . import epics, log

ENUM_KEYS = [
    'ZR', 'ON', 'TW', 'TH', 'FR', 'FV', 'SX', 'SV',
    'EI', 'NI', 'TE', 'EL', 'TV', 'TT', 'FT', 'FF'
]

logger = log.get_module_logger(__name__)


class RecordType(type):
    """Record MetaClass"""

    def __new__(cls, name, bases, dct):
        # append required kwargs
        dct['required'] = getattr(bases[0], 'required', []) + dct.get('required', [])

        # update fields
        fields = {}
        fields.update(getattr(bases[0], 'fields', {}))
        fields.update(dct.get('fields'))
        dct['fields'] = fields

        return super(RecordType, cls).__new__(cls, name, bases, dct)


class Record(object):
    __metaclass__ = RecordType
    required = ['name', 'desc']
    record = 'ai'
    fields = {
        'DESC': '{desc}',
    }

    def __init__(self, name, desc=None, **kwargs):
        """
        Base class for all record types. Do not use directly.

        :param name: Record name (str)
        :param desc: Description (str)
        :param kwargs: additional keyword arguments
        """
        kwargs.update(name=name, desc=desc)
        kw = {k: v for k, v in kwargs.items() if v is not None}
        self.options = {}
        self.options.update(kw)
        self.options['record'] = self.record
        self.instance_fields = {}
        self.instance_fields.update(self.fields)
        missing_args = set(self.required) - set(self.options.keys())
        assert not missing_args, '{}: Missing required kwargs: "{}"'.format(self.__class__.__name__,
                                                                            ', '.join(missing_args))

    def __str__(self):
        template = '\n'.join(
            ['record({record}, "$(device):{name}") {{'] +
            ['  field({}, "{}")'.format(k, v) for k, v in self.instance_fields.items()] +
            ['}}', '']
        )
        return template.format(**self.options)

    def add_field(self, key, value):
        """
        Add a database record field

        :param key: field name
        :param value: field value
        :return:
        """
        self.instance_fields[key] = value

    def del_field(self, key):
        """
        Delete a database record field

        :param key: field name
        """
        if key in self.instance_fields:
            del self.instance_fields[key]


class Enum(Record):
    required = ['choices']
    record = 'mbbo'
    fields = {
        'VAL': '{default}'
    }

    def __init__(self, name, choices=None, default=0, **kwargs):
        """
        Enum record type

        :param name: Record name (str)
        :param choices: list/tuple of strings corresponding to the choice names, values will be 0-index integers
        :param default: default value of the record, 0 by default
        :param kwargs: Extra keyword arguments
        """
        kwargs.update(choices=choices, default=default)
        super(Enum, self).__init__(name, **kwargs)
        if isinstance(self.options['choices'], EnumMeta):
            choice_pairs = [(e.name, e.value) for e in self.options['choices']]
        elif isinstance(self.options['choices'], collections.Iterable):
            choice_pairs = [(c, i) for i, c in enumerate(self.options['choices'])]
        else:
            choice_pairs = []
        for i in range(len(choice_pairs)):
            name, value = choice_pairs[i]
            key = ENUM_KEYS[i]
            self.add_field('{}VL'.format(key), "{}".format(value))
            self.add_field('{}ST'.format(key), name)


class BinaryOutput(Record):
    record = 'mbboDirect'
    fields = {
        'VAL': '{default}',
        'OUT': '{out}',
        'SHFT': '{shift}',
    }

    def __init__(self, name, default=0, out='', shift=0, **kwargs):
        """
        Binary record type for converting between integers and bits

        :param name: Record name (str)
        :param default: default value of the record, 0 by default
        :param out: output link
        :param shift: shift value by this number of bits to the right
        :param kwargs: Extra keyword arguments
        """
        kwargs.update(default=default, out=out, shift=shift)
        super(BinaryOutput, self).__init__(name, **kwargs)


class BinaryInput(Record):
    record = 'mbbiDirect'
    fields = {
        'VAL': '{default}',
        'INP': '{inp}',
        'SHFT': '{shift}',
    }

    def __init__(self, name, default=0, inp='', shift=0, **kwargs):
        """
        Binary record type for converting between integers and bits

        :param name: Record name (str)
        :param inp: Input link
        :param shift: shift value by this number of bits to the right
        :param default: default value of the record, 0 by default
        :param kwargs: Extra keyword arguments
        """
        kwargs.update(default=default, inp=inp, shift=shift)
        super(BinaryInput, self).__init__(name, **kwargs)


class Toggle(Record):
    record = 'bo'
    fields = {
        'ZNAM': '{zname}',
        'ONAM': '{oname}',
        'HIGH': '{high:0.2g}'
    }

    def __init__(self, name, high=0.25, zname=None, oname=None, **kwargs):
        """
        Toggle field corresponding to a binary out record.

        :param name: Record name (str)
        :param high: Duration to keep high before returning to zero
        :param zname: string value when zero
        :param oname: string value when high
        :param kwargs: Extra keyword arguments
        """
        zname = kwargs['desc'] if not zname else zname
        oname = kwargs['desc'] if not oname else oname
        kwargs.update(high=high, zname=zname, oname=oname)
        super(Toggle, self).__init__(name, **kwargs)


class String(Record):
    required = ['max_length']
    record = 'stringout'
    fields = {
        'VAL': '{default}'
    }

    def __init__(self, name, max_length=20, default=' ', **kwargs):
        """
        String record. Uses standard string record, or character array depending on length

        :param name: Record name (str)
        :param max_length: maximum number of characters expected
        :param default:  default value, empty string by default
        :param kwargs: Extra keyword arguments
        """
        kwargs.update(max_length=max_length, default=default)
        super(String, self).__init__(name, **kwargs)
        if self.options['max_length'] > 40:
            self.options['record'] = 'waveform'
            self.add_field('NELM', self.options['max_length'])
            self.add_field('FTVL', 'CHAR')
            self.del_field('VAL')


class Integer(Record):
    record = 'longout'
    required = ['units']
    fields = {
        'HOPR': '{max_val}',
        'LOPR': '{min_val}',
        'DRVH': '{max_val}',
        'DRVL': '{min_val}',
        'VAL': '{default}',
        'EGU': '{units}',
    }

    def __init__(self, name, max_val=0, min_val=0, default=0, units='', **kwargs):
        """
        Integer Record.

        :param name: Record Name.
        :param max_val: Maximum value permitted (int), default (no limit)
        :param min_val: Minimum value permitted (int), default (no limit)
        :param default: default value, default (0)
        :param units:  engineering units (str), default empty string
        :param kwargs: Extra keyword arguments
        """
        kwargs.update(max_val=max_val, min_val=min_val, default=default, units=units)
        super(Integer, self).__init__(name, **kwargs)


class Float(Record):
    record = 'ao'
    required = ['units']
    fields = {
        'DRVL': '{max_val:0.4e}',
        'DRVH': '{min_val:0.4e}',
        'LOPR': '{max_val:0.4e}',
        'HOPR': '{min_val:0.4e}',
        'PREC': '{prec}',
        'EGU': '{units}',
        'VAL': '{default}'
    }

    def __init__(self, name, max_val=0, min_val=0, default=0.0, prec=4, units='', **kwargs):
        """
        Float Record.

        :param name: Record Name.
        :param max_val: Maximum value permitted (float), default (no limit)
        :param min_val: Minimum value permitted (float), default (no limit)
        :param default: default value, default (0.0)
        :param prec: number of decimal places, default (4)
        :param units:  engineering units (str), default empty string
        :param kwargs: Extra keyword arguments
        """
        kwargs.update(max_val=max_val, min_val=min_val, default=default, prec=prec, units=units)
        super(Float, self).__init__(name, **kwargs)


class Calc(Record):
    record = 'calc'
    required = ['calc']
    defaults = {
        'scan': 0,
        'prec': 4,
    }
    fields = {
        'CALC': '{calc}',
        'SCAN': '{scan}',
        'PREC': '{prec}',
    }

    def __init__(self, name, scan=0, prec=4, **kwargs):
        """
        Calc Record

        :param name: Record name
        :param scan: scan parameter, default (0 ie passive)
        :param prec: number of decimal places, default (4)
        :param kwargs: Extra keyword arguments
        """
        kwargs.update(scan=scan, prec=prec)
        super(Calc, self).__init__(name, **kwargs)
        for c in 'ABCDEFGHIJKL':
            key = 'INP{}'.format(c)
            if key.lower() in self.options:
                self.add_field(key, self.options[key.lower()])


class CalcOut(Calc):
    record = 'calcout'
    fields = {
        'OOPT': 0,
        'DOPT': 0,
        'OUT': '{out}'
    }

    def __init__(self, name, out='', **kwargs):
        """
        CalcOutput Record

        :param name: Record name
        :param out: Output record
        :param kwargs: Extra keyword arguments, supports Calc kwargs also.
        """
        kwargs.update(out=out)
        super(CalcOut, self).__init__(name, **kwargs)


class Array(Record):
    record = 'waveform'
    required = ['type', 'length']
    fields = {
        'NELM': '{length}',
        'FTVL': '{type}',
    }

    def __init__(self, name, type=int, length=None, **kwargs):
        """
        Array Record.

        :param name: Record Name
        :param type: Element type (str or python type), supported types are ['STRING', 'SHORT', 'FLOAT', int, str, float]
        :param length: Number of elements in the array
        :param kwargs: Extra kwargs
        """
        kwargs.update(type=type, length=length)
        super(Array, self).__init__(name, **kwargs)
        element_type = self.options['type']
        self.options['type'] = {
            str: 'STRING',
            int: 'LONG',
            float: 'FLOAT',
        }.get(element_type, element_type)


CMD_TEMPLATE = """
## Load record instances
dbLoadRecords("{db_name}.db", "{macros}")
iocInit()
dbl
"""


class ModelType(type):
    def __new__(cls, name, bases, dct):
        fields = {}
        for k, v in dct.items():
            if isinstance(v, Record):
                fields[k] = v
                del dct[k]
        dct['_fields'] = fields
        return super(ModelType, cls).__new__(cls, name, bases, dct)


class Model(object):
    __metaclass__ = ModelType

    def __init__(self, device_name, callbacks=None, command='softIoc', macros=None):
        """
        IOC Database Model

        :param device_name:  Root Name of device
        :param callbacks: Callback handler which provides callback methods for handling events and commands
        :param command: The softIoc command to execute. By default this is 'softIoc' from EPICS base.
        :param macros: additional macros to be used in the database as a dictionary

        Process Variable records will be named *<device_name>:<record_name>*.

        If Callback Handler is not provided, it is assumed that all callbacks are defined within the model itself.
        The expected callback methods must follow the signature:

        .. code-block:: python

            def do_<record_name>(self, pv, value, ioc):
                ...

        which accepts the active record (pv), the changed value (value) and the ioc instance (ioc). If the Model
        is also the callbacks provider, self, and ioc are identical, otherwise ioc is a reference to the database
        model on which the record resides.
        """
        self.device_name = device_name
        self.callbacks = callbacks or self
        self.ioc_process = None
        self.macros = {'device': self.device_name}
        if isinstance(macros, dict):
            self.macros.update(**macros)
        self.command = command
        self.ready = False
        self.db_cache_dir = os.path.join(os.path.join(os.getcwd(), '__dbcache__'))
        self.directory = os.getcwd()
        self._startup()
        self._setup()

    def _startup(self):
        """
        Generate the database and start the IOC application in a separate process
        """
        if not os.path.exists(self.db_cache_dir):
            os.mkdir(self.db_cache_dir)
        db_name = self.__class__.__name__
        with open(os.path.join(self.db_cache_dir, '{}.db'.format(db_name)), 'w') as db_file:
            for k, v in self._fields.items():
                db_file.write(str(v))

        with open(os.path.join(self.db_cache_dir, '{}.cmd'.format(db_name)), 'w') as cmd_file:
            macro_text = ','.join(['{}={}'.format(k,v) for k,v in self.macros.items()])


            cmd_file.write(CMD_TEMPLATE.format(macros=macro_text, db_name=db_name))
        os.chdir(self.db_cache_dir)
        self.ioc_process = multiprocessing.Process(
            target=subprocess.check_call,
            args=([self.command, '{}.cmd'.format(db_name)],),
            kwargs={'stdin': subprocess.PIPE}
        )
        self.ioc_process.daemon = True
        self.ioc_process.start()

    def shutdown(self):
        """
        Shutdown the ioc application
        """
        self.ioc_process.terminate()
        shutil.rmtree(self.db_cache_dir)

    def _setup(self):
        """
        Set up the ioc records an connect all callbacks
        """
        pending = set()
        for k, f in self._fields.items():
            pv_name = '{}:{}'.format(self.device_name, f.options['name'])
            pv = epics.PV(pv_name)
            pending.add(pv)
            setattr(self, k, pv)
            callback = 'do_{}'.format(k).lower()
            #REM print( '\tmydebug> ', pv, k, callback )
            if hasattr(self.callbacks, callback):
                pv.connect('changed', getattr(self.callbacks, callback), self)

        # wait 10 seconds for all PVs to connect
        timeout = 5
        while pending and timeout > 0:
            time.sleep(0.05)
            timeout -= 0.05
            pending = {pv for pv in pending if not pv.is_active()}

        print('')
