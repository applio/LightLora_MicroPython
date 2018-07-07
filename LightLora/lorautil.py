"Provides lightweight management for sx1276 chips"

from utime import sleep_ms
from LightLora import spicontrol, sx127x


#_BUFFER = bytearray(128)  # FIFO buffer size on ESP32 according to Arduino


class LoraPacket:
    def __init__(self):
        self.srcAddress = None
        self.dstAddress = None
        self.srcLineCount = None
        self.payLength = None
        self.msgTxt = None
        self.rssi = None
        self.snr = None

    def clear(self):
        self.msgTxt = ''

class LoraUtil:
    '''a LoraUtil object has an sx1276 and it can send and receive LoRa packets
       sendPacket -> send a string
       isPacketAvailable -> do we have a packet available?
       readPacket -> get the latest packet
    '''
    def __init__(self, **kwargs):
        # just be neat and init variables in the __init__
        self.linecounter = 0
        self.packet = None
        self.doneTransmit = False

        # init spi
        self.spic = spicontrol.SpiControl(**kwargs)
        # init lora
        self.lora = sx127x.SX127x(spiControl=self.spic, **kwargs)
        self.spic.init_lora_pins()
        self.lora.init()
        self.lora.onReceive(self._doReceive)
        self.lora.onTransmit(self._doTransmit)
        # put into receive mode and wait for an interrupt
        self.lora.receive()

    # we received a packet, deal with it
    def _doReceive(self, sx12, pay):
        pkt = LoraPacket()
        self.packet = None
        if pay and len(pay) > 4:
            pkt.srcAddress = pay[0]
            pkt.dstAddress = pay[1]
            pkt.srcLineCount = pay[2]
            pkt.payLength = pay[3]
            pkt.rssi = sx12.packetRssi()
            pkt.snr = sx12.packetSnr()
            try:
                pkt.msgTxt = pay[4:].decode('utf-8', 'ignore')
            except Exception as ex:
                print("doReceiver error: ")
                print(ex)
            self.packet = pkt

    def _doTransmit(self):
        # Run when the transmit has ended
        self.doneTransmit = True
        self.lora.receive() # wait for a packet (?)

    def writeInt(self, value):
        self.lora.write(bytearray([value]))

    def sendPacket(self, dstAddress, localAddress, outGoing):
        '''send a packet of header info and a bytearray to dstAddress'''
        try:
            self.linecounter = self.linecounter + 1
            self.doneTransmit = False
            self.lora.beginPacket()
            self.writeInt(dstAddress)
            self.writeInt(localAddress)
            self.writeInt(self.linecounter)
            self.writeInt(len(outGoing))
            self.lora.write(outGoing)
            self.lora.endPacket()
            slt = 0
            while (not self.doneTransmit) and (slt < 50):
                sleep_ms(100)
                slt = slt + 1
            if slt == 50:
                print("Transmit timeout")
        except Exception as ex:
            print(str(ex))

    def isPacketAvailable(self):
        # Convert to bool result from None or True
        return True if self.packet else False

    def readPacket(self):
        "Return the current packet (or none) and clear it out"
        pkt = self.packet
        self.packet = None
        return pkt

