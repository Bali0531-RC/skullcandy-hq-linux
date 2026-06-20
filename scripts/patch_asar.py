#!/usr/bin/env python3
"""
patch_asar.py - inject a Linux USB-detection fallback into Skull-HQ's app.asar.

Why
---
Under Wine, node-hid's device enumeration returns no Skullcandy device, so the
app never starts talking to the headset. This patch makes headset.service.js fall
back to reading USB device descriptors straight from the Linux host (via Wine's
Z: drive -> /dev/bus/usb) when node-hid comes back empty. Combined with the
hid.dll bridge, the headset is then fully detected and controlled.

The patch is:
  * minimal   - injects one helper function and rewrites two identical lines
  * idempotent- running it twice is a no-op
  * format-safe - it edits the asar in place at the byte level, preserving the
    original archive layout (offsets, integrity hashes) which the bundled
    Electron build verifies. It does NOT use `asar pack` (that drops the
    `*.unpacked` native-module links and breaks the app).

Usage:
  patch_asar.py /path/to/resources/app.asar          # patch (makes app.asar.bak)
  patch_asar.py --revert /path/to/resources/app.asar # restore from app.asar.bak
"""
import sys, os, json, struct, hashlib

VENDOR_DEC = 13552  # 0x34F0 Skullcandy
BLOCK = 4 * 1024 * 1024
MARKER = "__skdyLinuxFallback"

HELPER_LINES = [
    'function ' + MARKER + '(usbDevices) {',
    '    try {',
    '        var hid = (usbDevices || []).filter(function (d) { return d.vendorId === ' + str(VENDOR_DEC) + '; });',
    '        if (hid.length > 0) return usbDevices;',
    '        var result = [];',
    '        var busDir = "Z:\\\\dev\\\\bus\\\\usb";',
    '        var buses = node_fs_1.default.readdirSync(busDir);',
    '        for (var i = 0; i < buses.length; i++) {',
    '            var devDir = busDir + "\\\\" + buses[i];',
    '            var devs = node_fs_1.default.readdirSync(devDir);',
    '            for (var j = 0; j < devs.length; j++) {',
    '                try {',
    '                    var fd = node_fs_1.default.openSync(devDir + "\\\\" + devs[j], "r");',
    '                    var buf = Buffer.alloc(18);',
    '                    node_fs_1.default.readSync(fd, buf, 0, 18, 0);',
    '                    node_fs_1.default.closeSync(fd);',
    '                    if (buf.readUInt16LE(8) === ' + str(VENDOR_DEC) + ') {',
    '                        result.push({ vendorId: buf.readUInt16LE(8), productId: buf.readUInt16LE(10) });',
    '                    }',
    '                } catch (e) {}',
    '            }',
    '        }',
    '        return result.length > 0 ? result : usbDevices;',
    '    } catch (e) { return usbDevices; }',
    '}',
]

IMPORT_ANCHOR = 'const node_path_1 = __importDefault(require("node:path"));'
IMPORT_ADD = 'const node_fs_1 = __importDefault(require("node:fs"));'
DEVICES_CALL = 'const usbDevices = node_hid_1.default.devices();'
DEVICES_PATCHED = 'const usbDevices = ' + MARKER + '(node_hid_1.default.devices());'


def transform(src: str) -> str:
    if MARKER in src:
        return src  # already patched
    if IMPORT_ANCHOR not in src:
        raise SystemExit("anchor not found: node:path import (unexpected app version)")
    if src.count(DEVICES_CALL) < 1:
        raise SystemExit("anchor not found: node_hid_1.default.devices() (unexpected app version)")
    eol = '\r\n' if '\r\n' in src else '\n'
    helper = eol.join(HELPER_LINES)
    injection = IMPORT_ANCHOR + eol + IMPORT_ADD + eol + helper
    # 1. add node:fs import + inject helper right after the node:path import
    src = src.replace(IMPORT_ANCHOR, injection, 1)
    # 2. route both enumeration sites (searchSupportedDevice + deviceVerification)
    src = src.replace(DEVICES_CALL, DEVICES_PATCHED)
    return src


def read_header(data: bytes):
    header_size = struct.unpack('<I', data[12:16])[0]
    hdr = json.loads(data[16:16 + header_size].decode('utf-8').rstrip('\x00'))
    return header_size, hdr


def find_entry(node, target_suffix, prefix=""):
    for k, v in node.items():
        cur = f"{prefix}/{k}" if prefix else k
        if 'files' in v:
            r = find_entry(v['files'], target_suffix, cur)
            if r:
                return r
        elif cur.endswith(target_suffix):
            return cur, v
    return None


def collect(node, out, prefix=""):
    for k, v in node.items():
        cur = f"{prefix}/{k}" if prefix else k
        if 'files' in v:
            collect(v['files'], out, cur)
        elif 'offset' in v:
            out.append((cur, v, int(v['offset'])))


def patch(asar_path: str):
    bak = asar_path + ".bak"
    # Always patch from a pristine copy so re-runs are clean.
    if not os.path.exists(bak):
        import shutil
        shutil.copy2(asar_path, bak)
        base = asar_path
    else:
        base = bak
    with open(base, 'rb') as f:
        data = f.read()

    header_size, hdr = read_header(data)
    target = 'dist-electron/headset/headset.service.js'
    found = find_entry(hdr['files'], target)
    if not found:
        raise SystemExit("headset.service.js not found in asar")
    _, entry = found
    old_off, old_size = int(entry['offset']), int(entry['size'])
    data_start = 16 + header_size
    src = data[data_start + old_off: data_start + old_off + old_size].decode('utf-8')

    new_src = transform(src).encode('utf-8')
    if new_src == src.encode('utf-8'):
        print("already patched; nothing to do")
        # still ensure the live file equals base (idempotent)
        if base != asar_path:
            with open(asar_path, 'wb') as f:
                f.write(data)
        return
    new_size = len(new_src)
    diff = new_size - old_size

    # shift offsets of every entry that comes after our file
    entries = []
    collect(hdr['files'], entries)
    entries.sort(key=lambda x: x[2])
    for path, e, off in entries:
        if off > old_off:
            e['offset'] = str(off + diff)
    # update our entry
    entry['size'] = new_size
    entry['integrity'] = {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(new_src).hexdigest(),
        "blockSize": BLOCK,
        "blocks": [hashlib.sha256(new_src[i:i + BLOCK]).hexdigest() for i in range(0, new_size, BLOCK)],
    }

    header_json = json.dumps(hdr, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    padded = ((len(header_json) + 3) // 4) * 4
    header_padded = header_json + b'\x00' * (padded - len(header_json))

    body = data[data_start:]
    new_body = body[:old_off] + new_src + body[old_off + old_size:]

    with open(asar_path, 'wb') as f:
        f.write(struct.pack('<I', 4))
        f.write(struct.pack('<I', padded + 8))
        f.write(struct.pack('<I', padded + 4))
        f.write(struct.pack('<I', padded))
        f.write(header_padded)
        f.write(new_body)
    print(f"patched {asar_path}  (+{diff} bytes, backup at {bak})")


def revert(asar_path: str):
    bak = asar_path + ".bak"
    if not os.path.exists(bak):
        raise SystemExit("no backup (.bak) to revert from")
    import shutil
    shutil.copy2(bak, asar_path)
    print(f"reverted {asar_path} from {bak}")


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "--revert":
        revert(args[1])
    else:
        patch(args[0])


if __name__ == "__main__":
    main()
