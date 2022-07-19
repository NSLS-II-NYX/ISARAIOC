from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet import reactor
from sys import stdout

class Echo(Protocol):
    def dataReceived(self, data):
        print(data)

class EchoClientFactory(ReconnectingClientFactory):

    client = None

    def startedConnecting(self, connector):
        print 'Started to connect.'

    def buildProtocol(self, addr):
        print 'Connected.'
        print 'Resetting reconnection delay'
        self.client = Echo()
        self.resetDelay()
        return self.client

    def clientConnectionLost(self, connector, reason):
        print 'Lost connection.  Reason:', reason
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        print 'Connection failed. Reason:', reason
        ReconnectingClientFactory.clientConnectionFailed(self, connector,
                                                         reason)
# class EchoClientFactory(ClientFactory):
#     def startedConnecting(self, connector):
#         print 'Started to connect.'
# 
#     def buildProtocol(self, addr):
#         print 'Connected.'
#         return Echo()
# 
#     def clientConnectionLost(self, connector, reason):
#         print 'Lost connection.  Reason:', reason
# 
#     def clientConnectionFailed(self, connector, reason):
#         print 'Connection failed. Reason:', reason

echo = EchoClientFactory()
reactor.connectTCP('192.168.53.201', 1000, echo)
reactor.run()
