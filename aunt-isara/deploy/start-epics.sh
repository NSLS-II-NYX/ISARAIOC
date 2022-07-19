#/bin/bash

#/usr/local/bin/procServ -c /usr/local/epics/aunt-isara/instance/IOC0000-000 --noautorestart --logfile=/var/log/IOC0000-000.log --pidfile=/var/run/IOC0000-000.pid --port 20000 /usr/local/epics/aunt-isara/bin/runIOC.py --device IOC0000-000 --address 192.6.95.205 --commands 10000 --status 1000
/usr/local/bin/procServ -c /usr/local/epics/aunt-isara/instance/IOC0000-000 --noautorestart --pidfile=/var/run/IOC0000-000.pid --port 20000 /usr/local/epics/aunt-isara/bin/runIOC.py --device IOC0000-000 --address 192.6.95.205 --commands 10000 --status 1000
