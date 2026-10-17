# Install python3 HID package https://pypi.org/project/hid/
import hid
from time import sleep

# default is TinyUSB (0xcafe), Adafruit (0x239a), RaspberryPi (0x2e8a), Espressif (0x303a) VID
USB_VID = (0xcafe, 0x239a, 0x2e8a, 0x303a)

print("VID list: " + ", ".join('%02x' % v for v in USB_VID))

for vid in  USB_VID:
    for dict in hid.enumerate(vid):
        print(dict)
        dev = hid.Device(dict['vendor_id'], dict['product_id'])
        if dev:
            print("")
            str_out = b'\x00' # it must be preceded with 0x00 as dummy reportID

            str_out += b'\x01'
            dev.write(str_out)
            str_in = dev.read(64)
            print("Received from HID Device:", str_in, '\n')

            sleep(0.5)
            str_out = b'\x00' # it must be preceded with 0x00 as dummy reportID
            str_out += b'\x01'
            str_out += b'\x00'
            dev.write(str_out)
            str_in = dev.read(64)
            print("Received from HID Device:", str_in, '\n')
        

