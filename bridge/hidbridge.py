#!/usr/bin/env python3
"""
hidbridge: native Linux helper that bridges Skullcandy HID control-pipe traffic
to the Wine app via a localhost TCP socket.

Why this exists
---------------
The Skullcandy Airoha SDK (AirohaHidCoreLib.dll) talks to the headset using
Windows HID control-pipe reports (HidD_SetOutputReport / HidD_GetInputReport).
Under Wine those GET_REPORT calls come back empty, so the app connects but never
receives device info, battery, EQ, etc.

The headset actually answers on the control pipe FEATURE report, which the Linux
kernel exposes via the HIDIOCGFEATURE ioctl on /dev/hidrawN. Wine can't issue
that ioctl, but this native helper can. The Wine-side hid.dll shim forwards the
relevant report calls here.

Protocol (localhost TCP, default 127.0.0.1:38099)
  Request : [op:1][rid:1][len:2 LE][payload:len]
  Response: [status:1][len:2 LE][data:len]
  op = 1 WRITE      : write output report (payload). Airoha command.
  op = 2 GETFEATURE : HIDIOCGFEATURE for report id `rid`, `len` bytes -> data
  op = 3 SETFEATURE : HIDIOCSFEATURE (payload)
  op = 4 READ       : non-blocking interrupt IN read (best effort)
"""
import os, sys, fcntl, struct, socket, threading, glob, errno

HOST = os.environ.get("HIDBRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("HIDBRIDGE_PORT", "38099"))
# Skullcandy USB vendor id. Product id is optional; if set, only that model is used.
VENDOR = int(os.environ.get("HIDBRIDGE_VENDOR", "0x34F0"), 0)
PRODUCT = os.environ.get("HIDBRIDGE_PRODUCT")  # e.g. "0x2220"; None = any Skullcandy
PRODUCT = int(PRODUCT, 0) if PRODUCT else None

HIDIOCGRAWINFO = 0x80084803
def _IOC(d, t, n, size): return (d << 30) | (size << 16) | (ord(t) << 8) | n
def HIDIOCSFEATURE(l): return _IOC(3, 'H', 0x06, l)
def HIDIOCGFEATURE(l): return _IOC(3, 'H', 0x07, l)

def log(*a): print("[hidbridge]", *a, flush=True)

def raw_info(fd):
    info = fcntl.ioctl(fd, HIDIOCGRAWINFO, struct.pack("iHH", 0, 0, 0))
    bustype, vendor, product = struct.unpack("iHH", info)
    return vendor & 0xFFFF, product & 0xFFFF

def find_hidraw():
    for path in sorted(glob.glob("/dev/hidraw*")):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            vendor, product = raw_info(fd)
            if vendor == VENDOR and (PRODUCT is None or product == PRODUCT):
                log(f"using {path} vendor={vendor:04x} product={product:04x}")
                return fd, path
        except OSError:
            pass
        os.close(fd)
    return None, None

class Device:
    def __init__(self):
        self.lock = threading.Lock()
        self.fd = None
        self.path = None
        self.reopen()

    def reopen(self):
        if self.fd is not None:
            try: os.close(self.fd)
            except OSError: pass
            self.fd = None
        self.fd, self.path = find_hidraw()
        return self.fd is not None

    def ensure(self):
        if self.fd is None:
            self.reopen()
        return self.fd is not None

    def write(self, data):
        with self.lock:
            if not self.ensure(): return 0
            try:
                return os.write(self.fd, data)
            except OSError as e:
                log("write err", e); self.reopen(); return 0

    def get_feature(self, rid, length):
        with self.lock:
            if not self.ensure(): return b""
            buf = bytearray(length); buf[0] = rid
            try:
                return bytes(fcntl.ioctl(self.fd, HIDIOCGFEATURE(length), bytes(buf)))
            except OSError as e:
                if e.errno not in (errno.EAGAIN,):
                    log("getfeature err", e)
                return b""

    def set_feature(self, data):
        with self.lock:
            if not self.ensure(): return 0
            try:
                fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(data)), bytes(data)); return 1
            except OSError as e:
                log("setfeature err", e); return 0

    def read(self, length):
        with self.lock:
            if not self.ensure(): return b""
            try:
                return os.read(self.fd, length)
            except OSError as e:
                if e.errno != errno.EAGAIN: log("read err", e)
                return b""

dev = Device()

def recvall(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk: return None
        data += chunk
    return data

def handle(conn):
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        while True:
            hdr = recvall(conn, 4)
            if not hdr: break
            op, rid, length = hdr[0], hdr[1], hdr[2] | (hdr[3] << 8)
            # WRITE/SETFEATURE carry a payload; GETFEATURE/READ carry only a length.
            if op in (1, 3):
                payload = recvall(conn, length) if length else b""
                if payload is None: break
            else:
                payload = b""
            if op == 1:
                n = dev.write(payload)
                conn.sendall(bytes([1 if n > 0 else 0, 0, 0]))
            elif op == 2:
                data = dev.get_feature(rid, length if length else 63)
                conn.sendall(bytes([1 if data else 0, len(data) & 0xFF, (len(data) >> 8) & 0xFF]) + data)
            elif op == 3:
                st = dev.set_feature(payload)
                conn.sendall(bytes([st, 0, 0]))
            elif op == 4:
                data = dev.read(length if length else 63)
                conn.sendall(bytes([1 if data else 0, len(data) & 0xFF, (len(data) >> 8) & 0xFF]) + data)
            else:
                conn.sendall(bytes([0, 0, 0]))
    except (ConnectionError, OSError) as e:
        log("conn err", e)
    finally:
        conn.close()

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(8)
    log(f"listening on {HOST}:{PORT}, device={'OK' if dev.fd is not None else 'NOT FOUND (will retry on demand)'}")
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
