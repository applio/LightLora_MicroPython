"Provides lightweight management for sx1276 chips"

from utime import sleep_ms
from LightLora import spicontrol, sx127x



class LoraPacket:
    def __init__(self):
        self.src_address = None
        self.dst_address = None
        self.src_line_count = None
        self.pay_length = None
        self.msg = None
        self.rssi = None
        self.snr = None

    @property
    def msg_txt(self):
        return self.msg.decode('utf-8', 'ignore')

    def clear(self):
        self.msg = b''

class LoraUtil:
    '''a LoraUtil object has an sx1276 and it can send and receive LoRa packets
       send_packet -> send a string
       is_packet_available -> do we have a packet available?
       read_packet -> get the latest packet
    '''
    def __init__(self, **kwargs):
        self.linecounter = 0
        self.packet = None
        self.done_transmit = False

        # init spi
        self.spic = spicontrol.SpiControl(**kwargs)
        # init lora
        self.lora = sx127x.SX127x(spiControl=self.spic, **kwargs)
        self.spic.init_lora_pins()
        self.lora.init()
        self.lora.onReceive(self._do_receive)
        self.lora.onTransmit(self._do_transmit)
        # put into receive mode and wait for an interrupt
        self.lora.receive()

    def _do_receive(self, sx12, pay):
        "Callback function triggered when we receive a packet to deal with it."
        pkt = LoraPacket()
        self.packet = None
        if pay and len(pay) > 4:
            pkt.src_address = pay[0]
            pkt.dst_address = pay[1]
            pkt.src_line_count = pay[2]
            pkt.pay_length = pay[3]
            pkt.rssi = sx12.packetRssi()
            pkt.snr = sx12.packetSnr()
            pkt.msg = pay[4:]  # Slice creates a new bytes object.
            self.packet = pkt

    def _do_transmit(self):
        "Callback function triggered when transmission of a packet has ended."
        self.done_transmit = True
        self.lora.receive() # wait for a packet (?)

    def write_int(self, value):
        "Write an int (generally as a 2-byte) using the LoRa driver."
        self.lora.write(bytearray([value]))

    def send_packet(self, src_address, dst_address, outgoing_payload):
        "Send a packet of header info and a bytearray to dst_address."
        try:
            self.linecounter = self.linecounter + 1
            self.done_transmit = False
            self.lora.beginPacket()
            self.write_int(src_address)
            self.write_int(dst_address)
            self.write_int(self.linecounter)
            self.write_int(len(outgoing_payload))
            self.lora.write(outgoing_payload)
            self.lora.endPacket()
            slt = 0
            while (not self.done_transmit) and (slt < 50):
                sleep_ms(100)
                slt = slt + 1
            if slt == 50:
                print("Transmit timeout")
        except Exception as ex:
            print(str(ex))

    def is_packet_available(self):
        "Indicates whether a packet is available; use read_packet() to get it."
        return bool(self.packet)

    def read_packet(self):
        "Return the current packet (or None) and clear it out."
        pkt = self.packet
        self.packet = None
        return pkt

