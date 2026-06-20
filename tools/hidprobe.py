#!/usr/bin/env python3
"""
hidprobe.py - native Linux ground-truth probe for Skullcandy (Airoha) headsets.

Use this to confirm how YOUR headset answers, independent of Wine. It talks to
/dev/hidrawN directly: lists Skullcandy devices, sends an output report, and
reads the reply via the control-pipe FEATURE report (HIDIOCGFEATURE) and the
interrupt IN endpoint, printing both.

Examples
--------
List Skullcandy HID devices:
    ./hidprobe.py

Replay the SLYR Pro "get device info" command and read the FEATURE reply:
    ./hidprobe.py --send 060a00055a06000c0a0210e803 --get 0x07

  --send HEX   output report bytes (first byte = report id). Sent with write().
  --get  RID   report id to fetch via HIDIOCGFEATURE after sending (default 0x07).
  --vendor V   USB vendor id (default 0x34f0 Skullcandy).
  --product P  restrict to a product id (default: any Skullcandy).
"""
import os, sys, fcntl, struct, glob, errno, time, argparse

def _IOC(d, t, n, size): return (d << 30) | (size << 16) | (ord(t) << 8) | n
def HIDIOCGFEATURE(l): return _IOC(3, 'H', 0x07, l)
HIDIOCGRAWINFO = 0x80084803
HIDIOCGRAWNAME = lambda l: _IOC(2, 'H', 0x04, l)

def info(fd):
    bustype, vendor, product = struct.unpack(
        "iHH", fcntl.ioctl(fd, HIDIOCGRAWINFO, struct.pack("iHH", 0, 0, 0)))
    try:
        name = fcntl.ioctl(fd, HIDIOCGRAWNAME(256), bytes(256)).split(b"\x00")[0].decode(errors="replace")
    except OSError:
        name = "?"
    return bustype, vendor & 0xFFFF, product & 0xFFFF, name

def find(vendor, product):
    out = []
    denied = 0
    for path in sorted(glob.glob("/dev/hidraw*")):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EPERM):
                denied += 1
            continue
        try:
            bus, vid, pid, name = info(fd)
            if vid == vendor and (product is None or pid == product):
                out.append((path, vid, pid, name))
        except OSError:
            pass
        os.close(fd)
    return out, denied

def hexdump(data, n=48):
    return " ".join(f"{b:02x}" for b in data[:n]) + (" ..." if len(data) > n else "")

def ascii_of(data, n=48):
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data[:n])

def main():
    ap = argparse.ArgumentParser(description="Skullcandy/Airoha hidraw probe")
    ap.add_argument("--vendor", default="0x34f0")
    ap.add_argument("--product", default=None)
    ap.add_argument("--send", default=None, help="output report hex (1st byte=report id)")
    ap.add_argument("--get", default="0x07", help="report id for HIDIOCGFEATURE")
    ap.add_argument("--len", type=int, default=63, help="feature report length")
    args = ap.parse_args()
    vendor = int(args.vendor, 0)
    product = int(args.product, 0) if args.product else None

    devs, denied = find(vendor, product)
    if not devs:
        print(f"No HID devices for vendor {vendor:#06x}"
              f"{'' if product is None else f' product {product:#06x}'}.")
        if denied:
            print(f"({denied} hidraw node(s) were not readable — try the udev rule "
                  f"or: sudo chmod 0666 /dev/hidraw*)")
        print("Is the headset on USB (not Bluetooth)? Try: lsusb | grep 34f0")
        return 1
    print("Skullcandy HID devices:")
    for path, vid, pid, name in devs:
        print(f"  {path}  vid={vid:04x} pid={pid:04x}  {name}")

    if not args.send:
        print("\n(tip: pass --send HEX --get RID to exercise the control protocol)")
        return 0

    path = devs[0][0]
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    try:
        cmd = bytes.fromhex(args.send)
        n = os.write(fd, cmd)
        print(f"\nwrite({path}) report id {cmd[0]:#04x}: {n} bytes")

        rid = int(args.get, 0)
        time.sleep(0.03)
        buf = bytearray(args.len); buf[0] = rid
        try:
            res = bytes(fcntl.ioctl(fd, HIDIOCGFEATURE(args.len), bytes(buf)))
            print(f"HIDIOCGFEATURE(rid={rid:#04x}): {hexdump(res)}")
            print(f"  ascii: {ascii_of(res)}")
        except OSError as e:
            print(f"HIDIOCGFEATURE failed: {e}")

        # interrupt IN (most Airoha models do NOT answer here; shown for completeness)
        import select
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                data = os.read(fd, 64)
                print(f"interrupt IN read: {hexdump(data)}")
            except OSError as e:
                if e.errno != errno.EAGAIN:
                    print("read err", e)
        else:
            print("interrupt IN read: (nothing)")
    finally:
        os.close(fd)
    return 0

if __name__ == "__main__":
    sys.exit(main())
