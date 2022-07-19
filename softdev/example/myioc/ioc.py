from softdev import models

class MyIOC(models.Model):
    enum = models.Enum('enum', choices=['ZERO', 'ONE', 'TWO'], default=0, desc='Enum Test')
    toggle = models.Toggle('toggle', zname='ON', oname='OFF', desc='Toggle Test')
    sstring = models.String('sstring', max_length=20, desc='Short String Test')
    lstring = models.String('lstring', max_length=512, desc='Long String Test')
    intval = models.Integer('intval', max_val=1000, min_val=-1000, default=0, desc='Int Test')
    floatval = models.Float(
        'floatval', max_val=1e6, min_val=1e-6, default=0.0,
        prec=5, desc='Float Test'
    )
    floatout = models.Float('floatout', desc='Test Float Output')
    intarray = models.Array('intarray', type=int, length=16, desc='Int Array Test')
    floatarray = models.Array('floatarray', type=float, length=16, desc='Float Array Test')
    calc = models.Calc(
        'calc', calc='A+B',
        inpa='$(device):intval CP NMS',
        inpb='$(device):floatval CP NMS',
        desc='Calc Test'
    )

class MyIOCApp(object):

    def __init__(self, device_name):
        self.ioc = MyIOC(device_name, callbacks=self)

    def do_toggle(self, pv, value, ioc):
        """
        I am called whenever the `toggle` record's value changes
        """
        if value == 1:
            # Command activated, value will return to 0 after some time
            print('Toggle Changed Value', value)
            ioc.enum.put((ioc.enum.get() + 1) % 3, wait=True)  # cycle through values

    def do_enum(self, pv, value, ioc):
        print('New Enum Value', value)

    def shutdown(self):
        # needed for proper IOC shutdown
        self.ioc.shutdown()
