from utime import sleep_ms
from machine import Pin, SPI
from micropython import const

# Default pin assignments for SPI and LoRa board
PIN_ID_SCK = const(2)           # GPIO2
PIN_ID_MISO = const(4)          # GPIO4
PIN_ID_MOSI = const(12)         # GPIO12
PIN_ID_LORA_DIO0 = const(15)    # GPIO15
PIN_ID_LORA_SS = const(14)      # GPIO14
PIN_ID_LORA_RESET = const(27)   # GPIO27

# loraconfig is the project definition for pins <-> hardware

class SpiControl:
    "Simple higher-level SPI stuff"

    def __init__(self,
                 pin_id_sck=PIN_ID_SCK,
                 pin_id_miso=PIN_ID_MISO,
                 pin_id_mosi=PIN_ID_MOSI,
                 pin_id_lora_dio0=PIN_ID_LORA_DIO0,
                 pin_id_lora_ss=PIN_ID_LORA_SS,
                 pin_id_lora_reset=PIN_ID_LORA_RESET,
                 baudrate=5000000,
                 **kwargs):
        self.spi = SPI(
                1,
                baudrate=baudrate,
                polarity=0,
                phase=0,
                bits=8,
                firstbit=SPI.MSB,
                sck=Pin(pin_id_sck, Pin.OUT),
                mosi=Pin(pin_id_mosi, Pin.OUT),
                miso=Pin(pin_id_miso, Pin.IN)
        )
        self.pinss = Pin(pin_id_lora_ss, Pin.OUT)
        self.pinrst = Pin(pin_id_lora_reset, Pin.OUT)
        self.pin_id_lora_dio0 = pin_id_lora_dio0



    # sx127x transfer is always write 2 bytes while reading the second byte
    # a read doesn't write the second byte. a write returns the prior value
    # write register # = 0x80 | read register #
    def transfer(self, address, value=0x00):
        response = bytearray(1)
        self.pinss.value(0)    # hold chip select low
        self.spi.write(bytearray([address]))  # write register address

        # write or read register walue
        self.spi.write_readinto(bytearray([value]), response)

        self.pinss.value(1)
        return response

    def get_irq_pin(self):
        "Get handle on a machine.Pin() for the LoRa's DIO0."
        irq_pin = Pin(self.pin_id_lora_dio0, Pin.IN)
        return irq_pin

    def init_lora_pins(self):
        "Initialize the pins for the LoRa device after instantiation of SX127x."
        self.pinss.value(1)     # initialize CS to high (off)
        self.pinrst.value(1)    # do a reset pulse
        sleep_ms(10)
        self.pinrst.value(0)
        sleep_ms(10)
        self.pinrst.value(1)
