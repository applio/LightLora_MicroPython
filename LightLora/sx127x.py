'''Generic sx127x driver for the Semtech chipsets.
In particular, it has a minor tweak for the sx1276.

This code supports interrupt driven send and receive for maximum efficiency.
Call onReceive and onTransmit to define the interrupt handlers.
    Receive handler gets a packet of data
    Transmit handler is informed the transmit ended

Communications is handled by an SpiControl object wrapping SPI
'''


import gc
import _thread
from machine import Pin
from micropython import const

PA_OUTPUT_RFO_PIN = const(0)
PA_OUTPUT_PA_BOOST_PIN = const(1)

# registers
REG_FIFO = const(0x00)
REG_OP_MODE = const(0x01)
REG_FRF_MSB = const(0x06)
REG_FRF_MID = const(0x07)
REG_FRF_LSB = const(0x08)
REG_PA_CONFIG = const(0x09)
REG_LNA = const(0x0c)
REG_FIFO_ADDR_PTR = const(0x0d)

REG_FIFO_TX_BASE_ADDR = const(0x0e)
FifoTxBaseAddr = const(0x00)
# FifoTxBaseAddr = 0x80

REG_FIFO_RX_BASE_ADDR = const(0x0f)
FifoRxBaseAddr = const(0x00)
REG_FIFO_RX_CURRENT_ADDR = const(0x10)
REG_IRQ_FLAGS_MASK = const(0x11)
REG_IRQ_FLAGS = const(0x12)
REG_RX_NB_BYTES = const(0x13)
REG_PKT_RSSI_VALUE = const(0x1a)
REG_PKT_SNR_VALUE = const(0x1b)
REG_MODEM_CONFIG_1 = const(0x1d)
REG_MODEM_CONFIG_2 = const(0x1e)
REG_PREAMBLE_MSB = const(0x20)
REG_PREAMBLE_LSB = const(0x21)
REG_PAYLOAD_LENGTH = const(0x22)
REG_FIFO_RX_BYTE_ADDR = const(0x25)
REG_MODEM_CONFIG_3 = const(0x26)
REG_RSSI_WIDEBAND = const(0x2c)
REG_DETECTION_OPTIMIZE = const(0x31)
REG_DETECTION_THRESHOLD = const(0x37)
REG_SYNC_WORD = const(0x39)
REG_DIO_MAPPING_1 = const(0x40)
REG_VERSION = const(0x42)

# modes
MODE_LONG_RANGE_MODE = const(0x80)  # bit 7: 1 => LoRa mode
MODE_SLEEP = const(0x00)
MODE_STDBY = const(0x01)
MODE_TX = const(0x03)
MODE_RX_CONTINUOUS = const(0x05)
# MODE_RX_SINGLE = 0x06
# 6 is not supported on the 1276
MODE_RX_SINGLE = const(0x05)

# PA config
PA_BOOST = const(0x80)

# IRQ masks
IRQ_TX_DONE_MASK = const(0x08)
IRQ_PAYLOAD_CRC_ERROR_MASK = const(0x20)
IRQ_RX_DONE_MASK = const(0x40)
IRQ_RX_TIME_OUT_MASK = const(0x80)

# Buffer size
MAX_PKT_LENGTH = const(255)

# pass in non-default parameters for any/all options in the constructor parameters argument
DEFAULT_PARAMETERS = {
    'frequency': 915000000,
    'tx_power_level': 5,
    'signal_bandwidth': 125000,
    'spreading_factor': 7,
    'coding_rate': 5,
    'preamble_length': 8,
    'implicitHeader': False,
    'sync_word': 0x12,
    'enable_CRC': True,
}

REQUIRED_VERSION = const(0x12)

class SX127x:
    ''' Standard SX127x library. Requires an spicontrol.SpiControl instance for spiControl '''
    def __init__(self,
                 name='SX127x',
                 onReceive=None,
                 onTransmit=None,
                 spiControl=None,
                 **kwargs):

        self.name = name
        self.parameters = dict(DEFAULT_PARAMETERS)
        self.parameters.update(kwargs)
        self._onReceive = onReceive  # the onreceive function
        self._onTransmit = onTransmit   # the ontransmit function
        self.doAcquire = hasattr(_thread, 'allocate_lock') # micropython vs loboris
        if self.doAcquire :
            self._lock = _thread.allocate_lock()
        else :
            self._lock = True
        self._spiControl = spiControl   # the spi wrapper - see spicontrol.py
        self.irqPin = spiControl.get_irq_pin() # a way to need loracontrol only in spicontrol

    def init(self):
        # check version
        version = self.readRegister(REG_VERSION)
        if version != REQUIRED_VERSION:
            raise Exception('Unsupported version found: %r' % version)

        # put in LoRa and sleep mode
        self.sleep()

        # config
        _parameters = self.parameters  # local var to avoid repeated dot-lookup
        self.setFrequency(_parameters['frequency'])
        self.setSignalBandwidth(_parameters['signal_bandwidth'])

        # set LNA boost
        self.writeRegister(REG_LNA, self.readRegister(REG_LNA) | 0x03)

        # set auto AGC
        self.writeRegister(REG_MODEM_CONFIG_3, 0x04)

        self.setTxPower(_parameters['tx_power_level'])
        self._implicitHeaderMode = None
        self.implicitHeaderMode(_parameters['implicitHeader'])
        self.setSpreadingFactor(_parameters['spreading_factor'])
        self.setCodingRate(_parameters['coding_rate'])
        self.setPreambleLength(_parameters['preamble_length'])
        self.setSyncWord(_parameters['sync_word'])
        self.enableCRC(_parameters['enable_CRC'])

        # set base addresses
        self.writeRegister(REG_FIFO_TX_BASE_ADDR, FifoTxBaseAddr)
        self.writeRegister(REG_FIFO_RX_BASE_ADDR, FifoRxBaseAddr)

        self.standby()

    # start sending a packet (reset the fifo address, go into standby)
    def beginPacket(self, implicitHeaderMode=False):
        self.standby()
        self.implicitHeaderMode(implicitHeaderMode)
        # reset FIFO address and paload length
        self.writeRegister(REG_FIFO_ADDR_PTR, FifoTxBaseAddr)
        self.writeRegister(REG_PAYLOAD_LENGTH, 0)

    # finished putting packet into fifo, send it
    # non-blocking so don't immediately receive...
    def endPacket(self):
        ''' non-blocking end packet '''
        if self._onTransmit:
           # enable tx to raise DIO0
            self._prepIrqHandler(self._handleOnTransmit)           # attach handler
            self.writeRegister(REG_DIO_MAPPING_1, 0x40)        # enable transmit dio0
        else:
            self._prepIrqHandler(None)                          # no handler
        # put in TX mode
        self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_TX)

    def isTxDone(self):
        ''' if Tx is done return true, and clear irq register - so it only returns true once '''
        if self._onTransmit:
            print("Do not call isTxDone with transmit interrupts enabled. Use the callback.")
            return False
        irqFlags = self.getIrqFlags()
        if (irqFlags & IRQ_TX_DONE_MASK) == 0:
            return False
        # clear IRQ's
        self._collect_garbage()
        return True

    def write(self, buffer):
        currentLength = self.readRegister(REG_PAYLOAD_LENGTH)
        size = len(buffer)
        # check size
        size = min(size, (MAX_PKT_LENGTH - FifoTxBaseAddr - currentLength))
        # write data
        for i in range(size):
            self.writeRegister(REG_FIFO, buffer[i])
        # update length
        self.writeRegister(REG_PAYLOAD_LENGTH, currentLength + size)
        return size

    def acquire_lock(self, lock=False):
        if self._lock:
            # we have a lock object
            if self.doAcquire:
                if lock:
                    self._lock.acquire()
                else:
                    self._lock.release()
            # else lock the thread hard
            else:
                if lock:
                    _thread.lock()
                else:
                    _thread.unlock()

    def println(self, string, implicitHeader=False):
        self.acquire_lock(True)  # wait until RX_Done, lock and begin writing.
        self.beginPacket(implicitHeader)
        self.write(string.encode())
        self.endPacket()
        self.acquire_lock(False) # unlock when done writing

    def getIrqFlags(self):
        ''' get and reset the irq register '''
        irqFlags = self.readRegister(REG_IRQ_FLAGS)
        self.writeRegister(REG_IRQ_FLAGS, irqFlags)
        return irqFlags

    def packetRssi(self):
        return self.readRegister(REG_PKT_RSSI_VALUE) - (164 if self._frequency < 868E6 else 157)

    def packetSnr(self):
        return self.readRegister(REG_PKT_SNR_VALUE) * 0.25

    def standby(self):
        self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_STDBY)

    def sleep(self):
        self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_SLEEP)

    def setTxPower(self, level, outputPin=PA_OUTPUT_PA_BOOST_PIN):
        if outputPin == PA_OUTPUT_RFO_PIN:
            # RFO
            level = min(max(level, 0), 14)
            self.writeRegister(REG_PA_CONFIG, 0x70 | level)
        else:
            # PA BOOST
            level = min(max(level, 2), 17)
            self.writeRegister(REG_PA_CONFIG, PA_BOOST | (level - 2))

    # set the frequency band. passed in Hz
    # Frf register setting = Freq / FSTEP where
    # FSTEP = FXOSC/2**19 where FXOSC=32MHz. So FSTEP==61.03515625
    def setFrequency(self, frequency):
        self._frequency = frequency
        frfs = (int)(frequency / 61.03515625)
        self.writeRegister(REG_FRF_MSB, frfs >> 16)
        self.writeRegister(REG_FRF_MID, frfs >> 8)
        self.writeRegister(REG_FRF_LSB, frfs)

    def setSpreadingFactor(self, sf):
        sf = min(max(sf, 6), 12)
        self.writeRegister(REG_DETECTION_OPTIMIZE, 0xc5 if sf == 6 else 0xc3)
        self.writeRegister(REG_DETECTION_THRESHOLD, 0x0c if sf == 6 else 0x0a)
        self.writeRegister(REG_MODEM_CONFIG_2, (self.readRegister(REG_MODEM_CONFIG_2) & 0x0f) | ((sf << 4) & 0xf0))

    def setSignalBandwidth(self, sbw):
        bins = (7.8E3, 10.4E3, 15.6E3, 20.8E3, 31.25E3, 41.7E3, 62.5E3, 125E3, 250E3)
        bw = 9
        for i in range(len(bins)):
            if sbw <= bins[i]:
                bw = i
                break
        self.writeRegister(REG_MODEM_CONFIG_1, (self.readRegister(REG_MODEM_CONFIG_1) & 0x0f) | (bw << 4))

    def setCodingRate(self, denominator):
        ''' this takes a value of 5..8 as the denominator of 4/5, 4/6, 4/7, 5/8 '''
        denominator = min(max(denominator, 5), 8)
        cr = denominator - 4
        self.writeRegister(REG_MODEM_CONFIG_1, (self.readRegister(REG_MODEM_CONFIG_1) & 0xf1) | (cr << 1))

    def setPreambleLength(self, length):
        self.writeRegister(REG_PREAMBLE_MSB, (length >> 8) & 0xff)
        self.writeRegister(REG_PREAMBLE_LSB, (length >> 0) & 0xff)

    def enableCRC(self, enable_CRC=False):
        modem_config_2 = self.readRegister(REG_MODEM_CONFIG_2)
        config = modem_config_2 | 0x04 if enable_CRC else modem_config_2 & 0xfb
        self.writeRegister(REG_MODEM_CONFIG_2, config)

    def setSyncWord(self, sw):
        self.writeRegister(REG_SYNC_WORD, sw)

    def dumpRegisters(self):
        for i in range(128):
            print("0x{0:02x}: {1:02x}".format(i, self.readRegister(i)))

    def implicitHeaderMode(self, implicitHeaderMode=False):
        if self._implicitHeaderMode != implicitHeaderMode:  # set value only if different.
            self._implicitHeaderMode = implicitHeaderMode
            modem_config_1 = self.readRegister(REG_MODEM_CONFIG_1)
            config = modem_config_1 | 0x01 if implicitHeaderMode else modem_config_1 & 0xfe
            self.writeRegister(REG_MODEM_CONFIG_1, config)

    def _prepIrqHandler(self, handlefn):
        ''' attach the handler to the irq pin, disable if None '''
        if self.irqPin:
            if handlefn:
                self.irqPin.irq(handler=handlefn, trigger=Pin.IRQ_RISING)
            else:
                self.irqPin.irq(handler=None, trigger=0)

    def onReceive(self, callback):
        ''' establish a callback function for receive interrupts'''
        self._onReceive = callback
        self._prepIrqHandler(None) # in case we have one and we're receiving. stop.

    def onTransmit(self, callback):
        ''' establish a callback function for transmit interrupts'''
        self._onTransmit = callback

    def receive(self, size=0):
        ''' enable reception - call this when you want to receive stuff '''
        self.implicitHeaderMode(size > 0)
        if size > 0:
            self.writeRegister(REG_PAYLOAD_LENGTH, size & 0xff)
        # enable rx to raise DIO0
        if self._onReceive:
            self._prepIrqHandler(self._handleOnReceive)         # attach handler
            self.writeRegister(REG_DIO_MAPPING_1, 0x00)
        else:
            self._prepIrqHandler(None)                          # no handler
        # The last packet always starts at FIFO_RX_CURRENT_ADDR
        # no need to reset FIFO_ADDR_PTR
        self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_RX_CONTINUOUS)

    # got a receive interrupt, handle it
    def _handleOnReceive(self, event_source):
        self.acquire_lock(True)           # lock until TX_Done
        irqFlags = self.getIrqFlags()
        irqBad = IRQ_PAYLOAD_CRC_ERROR_MASK | IRQ_RX_TIME_OUT_MASK
        if (irqFlags & IRQ_RX_DONE_MASK) and \
           ((irqFlags & irqBad) == 0) and \
            self._onReceive:
            # it's a receive data ready interrupt
            payload = self.read_payload()
            self.acquire_lock(False)     # unlock when done reading
            self._onReceive(self, payload)
        else:
            self.acquire_lock(False)             # unlock in any case.
            if not irqFlags & IRQ_RX_DONE_MASK:
                print("not rx done mask")
            elif (irqFlags & IRQ_PAYLOAD_CRC_ERROR_MASK) != 0:
                print("crc error")
            elif (irqFlags & IRQ_RX_TIME_OUT_MASK) != 0:
                print("receive timeout error")
            else:
                print("no receive method defined")

    # Got a transmit interrupt, handle it
    def _handleOnTransmit(self, event_source):
        self.acquire_lock(True)           # lock until flags cleared
        irqFlags = self.getIrqFlags()
        if irqFlags & IRQ_TX_DONE_MASK:
            # it's a transmit finish interrupt
            self._prepIrqHandler(None)     # disable handler since we're done
            self.acquire_lock(False)             # unlock
            if self._onTransmit:
                self._onTransmit()
            else:
                print("transmit callback but no callback method")
        else:
            self.acquire_lock(False)             # unlock
            print("transmit callback but not txdone: " + str(irqFlags))

    def receivedPacket(self, size=0):
        ''' when no receive handler, this tells if packet ready. Preps for receive'''
        if self._onReceive:
            print("Do not call receivedPacket. Use the callback.")
            return False
        irqFlags = self.getIrqFlags()
        self.implicitHeaderMode(size > 0)
        if size > 0:
            self.writeRegister(REG_PAYLOAD_LENGTH, size & 0xff)
        # if (irqFlags & IRQ_RX_DONE_MASK) and \
           # (irqFlags & IRQ_RX_TIME_OUT_MASK == 0) and \
           # (irqFlags & IRQ_PAYLOAD_CRC_ERROR_MASK == 0):
        if irqFlags == IRQ_RX_DONE_MASK:  # RX_DONE only, irqFlags should be 0x40
            # automatically standby when RX_DONE
            return True
        elif self.readRegister(REG_OP_MODE) != (MODE_LONG_RANGE_MODE | MODE_RX_SINGLE):
            # no packet received and not in receive mode
            # reset FIFO address / # enter single RX mode
            self.writeRegister(REG_FIFO_ADDR_PTR, FifoRxBaseAddr)
            self.writeRegister(REG_OP_MODE, MODE_LONG_RANGE_MODE | MODE_RX_SINGLE)
        return False

    def read_payload(self):
        # set FIFO address to current RX address
        # fifo_rx_current_addr = self.readRegister(REG_FIFO_RX_CURRENT_ADDR)
        self.writeRegister(REG_FIFO_ADDR_PTR, self.readRegister(REG_FIFO_RX_CURRENT_ADDR))
        # read packet length
        packetLength = self.readRegister(REG_PAYLOAD_LENGTH) if self._implicitHeaderMode else \
                       self.readRegister(REG_RX_NB_BYTES)
        payload = bytearray()
        for i in range(packetLength):
            payload.append(self.readRegister(REG_FIFO))
        self._collect_garbage()
        return bytes(payload)

    def readRegister(self, address, byteorder='big', signed=False):
        response = self._spiControl.transfer(address & 0x7f)
        return int.from_bytes(response, byteorder)

    def writeRegister(self, address, value):
        self._spiControl.transfer(address | 0x80, value)

    def _collect_garbage(self):
        gc.collect()
        #print('[Memory - free: {}   allocated: {}]'.format(gc.mem_free(), gc.mem_alloc()))
