#!/usr/bin/env python3
# HIDCMD v1 LED control tester for the RP2350-USB-C native-USB port.
#
# Install python3 HID package https://pypi.org/project/hid/
#   pip install hid
#
# Speaks the protocol documented in hid-cmd-protocol.md: §4.2 LED_SET plus
# the universal ACK / ERROR frames (§5). The device is a pure LED controller
# with one onboard WS2812B (fixed color blue), so valid led_ids are 1 and
# 0xFF (all); every other command ID must be answered with ERROR 0x01.
#
# Usage: python3 hid-led-test.py [vid] [pid]     # hex, e.g. 2e8a 4004
#   defaults to the native port 0x2e8a:0x4004. Plug in only the native USB-C
#   port for a clean run (the PIO-USB cafe:0000 device has no OUT endpoint).

import sys
import time

import hid

REPORT_SIZE = 64            # one HID report = one frame (§2)
MAX_PARAMS = REPORT_SIZE - 2

CMD_ACK     = 0x00          # D->H, fixed value 0x00 ("received")
CMD_LED_SET = 0x01          # H->D: [led_id][mode]
CMD_ERROR   = 0xFD          # D->H: [failed cmd][error code]

ERR_UNKNOWN_CMD = 0x01      # unknown command ID (§4.7)
ERR_MALFORMED   = 0x02      # LEN > 62 or non-zero padding after LEN
ERR_PARAM_RANGE = 0x03      # parameter out of range

LED_OFF, LED_ON, LED_BLINK = 0x00, 0x01, 0x02
LED_ALL = 0xFF

# default is TinyUSB (0xcafe), Adafruit (0x239a), RaspberryPi (0x2e8a), Espressif (0x303a) VID
USB_VID = (0xcafe, 0x239a, 0x2e8a, 0x303a)

DEFAULT_VID, DEFAULT_PID = 0x2e8a, 0x4004


def find_device(vid=None, pid=None):
    """Open the HID device. Prefers the native RP2350 port (2e8a:4004)."""
    if vid is not None and pid is not None:
        candidates = hid.enumerate(vid, pid)
    else:
        # try the native port first, then any other known VID
        vids = [DEFAULT_VID] + [v for v in USB_VID if v != DEFAULT_VID]
        candidates = []
        for v in vids:
            candidates.extend(hid.enumerate(v))

    for d in candidates:
        print("found:", d['path'], hex(d['vendor_id']), hex(d['product_id']))
        dev = hid.Device(d['vendor_id'], d['product_id'])
        if dev:
            return dev
    return None


def send(dev, cmd, params=b''):
    """Send one full 64-byte frame (zero-padded) with the dummy report ID."""
    assert len(params) <= MAX_PARAMS
    frame = bytearray(REPORT_SIZE)
    frame[0] = cmd
    frame[1] = len(params)
    frame[2:2 + len(params)] = params
    dev.write(b'\x00' + bytes(frame))   # dummy report ID for hidraw


def send_raw(dev, frame):
    """Send an exact 64-byte frame (for malformed-frame tests)."""
    assert len(frame) == REPORT_SIZE
    dev.write(b'\x00' + bytes(frame))


def recv(dev, timeout_ms=100):
    """Read one IN report -> (cmd, params), or None on timeout."""
    data = dev.read(REPORT_SIZE + 1, timeout_ms)
    if not data:
        return None
    # hidraw prepends a report-ID byte; libhidapi strips it when the device
    # has no numbered reports (verified here: read returns exactly 64 bytes).
    if len(data) == REPORT_SIZE + 1 and data[0] == 0x00:
        frame = bytes(data[1:])
    else:
        frame = bytes(data[:REPORT_SIZE])
    return frame[0], bytes(frame[2:2 + frame[1]])


def drain(dev, timeout_ms=20):
    """Discard any IN reports left over from a previous step."""
    while recv(dev, timeout_ms) is not None:
        pass


def command(dev, cmd, params=b'', expect=None):
    """Send a command; read its ACK, then (if `expect` given) the response.

    Returns (ack, resp); each is (cmd, params) or None on timeout."""
    drain(dev)                       # stale frames belong to the last step
    send(dev, cmd, params)
    ack = recv(dev)                  # expect (0x00, b'\x00')
    resp = None
    if expect is not None:
        for _ in range(4):           # skip interleaved unsolicited frames
            got = recv(dev)          # (e.g. SWITCH_EVENT 0x40 on other devices)
            if got is None or got[0] != 0x40:
                resp = got
                break
    return ack, resp


def fmt(frame):
    if frame is None:
        return "timeout"
    cmd, params = frame
    return f"cmd=0x{cmd:02X} len={len(params)} params={params.hex(' ')}"


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def run_tests(dev):
    failures = 0

    def expect_ack(name, got):
        nonlocal failures
        ok = got is not None and got[0] == CMD_ACK and got[1] == b'\x00'
        if not check(f"{name}: ACK", ok, f"expected (00 01 00), got {fmt(got)}"):
            failures += 1

    def expect_error(name, got, cmd, code):
        nonlocal failures
        want = bytes([cmd, code])
        ok = got is not None and got[0] == CMD_ERROR and got[1] == want
        if not check(f"{name}: ERROR [{cmd:02X} {code:02X}]", ok, f"got {fmt(got)}"):
            failures += 1

    print("== §4.2 LED_SET (the device LED is blue) ==")

    # 1. LED 1 on
    ack, _ = command(dev, CMD_LED_SET, bytes([1, LED_ON]))
    expect_ack("LED 1 ON", ack)
    time.sleep(1.0)                  # watch it light up

    # 2. LED 1 blink (500 ms on / off)
    ack, _ = command(dev, CMD_LED_SET, bytes([1, LED_BLINK]))
    expect_ack("LED 1 BLINK", ack)
    time.sleep(1.5)                  # watch it blink

    # 3. all LEDs off (led_id = 0xFF)
    ack, _ = command(dev, CMD_LED_SET, bytes([LED_ALL, LED_OFF]))
    expect_ack("ALL OFF (led_id=0xFF)", ack)
    time.sleep(0.3)

    # 4. default-LED shorthand: raw short reports (§4.2 special case)
    dev.write(b'\x00\x01')           # "01" -> default LED on
    expect_ack("shorthand '01' (default ON)", recv(dev))
    time.sleep(1.0)                  # watch it light up
    dev.write(b'\x00\x01\x00')       # "01 00" -> default LED off
    expect_ack("shorthand '01 00' (default OFF)", recv(dev))

    print("== error paths (§4.7) ==")

    # 5. led_id out of range (the device has one LED)
    ack, err = command(dev, CMD_LED_SET, bytes([2, LED_ON]), expect=CMD_ERROR)
    expect_ack("bad led_id: ACK", ack)
    expect_error("bad led_id (led_id=2)", err, CMD_LED_SET, ERR_PARAM_RANGE)

    # 6. invalid mode value
    ack, err = command(dev, CMD_LED_SET, bytes([1, 0x05]), expect=CMD_ERROR)
    expect_ack("bad mode: ACK", ack)
    expect_error("bad mode (mode=0x05)", err, CMD_LED_SET, ERR_PARAM_RANGE)

    # 7. unknown command (RELAY_SET on a pure LED controller -> 0x01)
    ack, err = command(dev, 0x20, bytes([1, 1]) + b'\x00' * 4, expect=CMD_ERROR)
    expect_ack("unknown cmd: ACK", ack)
    expect_error("unknown cmd (0x20 RELAY_SET)", err, 0x20, ERR_UNKNOWN_CMD)

    # 8. malformed frame: non-zero padding after LEN -> ERROR only, no ACK
    drain(dev)
    frame = bytearray(REPORT_SIZE)
    frame[0] = CMD_LED_SET
    frame[1] = 2
    frame[2], frame[3] = 1, LED_ON
    frame[4] = 0xAA                  # non-zero padding -> malformed (§5 rule 3)
    send_raw(dev, frame)
    got = recv(dev)
    ok = (got is not None and got[0] == CMD_ERROR
          and got[1] == bytes([CMD_LED_SET, ERR_MALFORMED]))
    if not check("malformed (padding): ERROR only, no ACK", ok, f"got {fmt(got)}"):
        failures += 1

    # 9. malformed frame: LEN > 62 -> ERROR only, no ACK
    drain(dev)
    frame = bytearray(REPORT_SIZE)
    frame[0] = CMD_LED_SET
    frame[1] = MAX_PARAMS + 1        # 63: invalid length
    send_raw(dev, frame)
    got = recv(dev)
    ok = (got is not None and got[0] == CMD_ERROR
          and got[1] == bytes([CMD_LED_SET, ERR_MALFORMED]))
    if not check("malformed (LEN=63): ERROR only, no ACK", ok, f"got {fmt(got)}"):
        failures += 1

    # leave the LED off
    command(dev, CMD_LED_SET, bytes([LED_ALL, LED_OFF]))
    return failures


def main():
    vid = pid = None
    if len(sys.argv) >= 3:
        vid, pid = int(sys.argv[1], 16), int(sys.argv[2], 16)

    print("VID list: " + ", ".join('%04x' % v for v in USB_VID))
    dev = find_device(vid, pid)
    if dev is None:
        print(f"no HID device found (tried {DEFAULT_VID:04x}:{DEFAULT_PID:04x} "
              f"and known VIDs)")
        print("plug the board's native USB-C port into the host")
        sys.exit(2)

    failures = run_tests(dev)
    dev.close()
    if failures:
        print(f"\n{failures} failure(s)")
        sys.exit(1)
    print("\nall tests passed")


if __name__ == '__main__':
    main()
