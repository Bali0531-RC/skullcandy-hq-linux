# Contributing

Thanks for helping extend this to more Skullcandy headsets (or improving the
Wine integration). Start with `docs/PROTOCOL.md` for how the device talks.

## Project layout

```
install.sh / uninstall.sh   orchestration
scripts/
  00-common.sh              shared paths/helpers (WINEPREFIX, INSTALL_DIR, finders)
  patch_asar.py             reversible, integrity-safe asar patch (Linux detection)
  build_dll.sh              build dll/hid_bridge.dll with mingw
bridge/hidbridge.py         native Linux HID helper (the part that does HIDIOCGFEATURE)
dll/
  hidbridge_dll.c           the hid.dll shim (routes Skullcandy report I/O to the helper)
  hid.def                   export list: forwards 39 fns to hidwine, wraps 5
  hid_bridge.dll            prebuilt x86_64
tools/
  hidprobe.py               native ground-truth probe (no Wine needed)
  hidlog.c                  logging pass-through hid.dll for capturing app traffic
docs/PROTOCOL.md            captured protocol notes
```

## Adding a new model — workflow

You need the headset on **USB** and (ideally) `mingw-w64-gcc` + `python3`.

### 1. Confirm the kernel sees it
```bash
lsusb | grep 34f0                 # note the PID
./tools/hidprobe.py               # lists Skullcandy /dev/hidraw* + names
```
If `hidprobe.py` can’t open the node, fix permissions (the udev rule, or a quick
`sudo chmod 0666 /dev/hidrawN`).

### 2. Ground-truth: does it answer via FEATURE reports?
Replay the SLYR Pro device-info command (harmless to try) and read the reply:
```bash
./tools/hidprobe.py --send 060a00055a06000c0a0210e803 --get 0x07
```
- If `HIDIOCGFEATURE` prints real bytes (often containing an `AB15xx` chip
  string) → **same transport → it will work through the existing bridge.** Often
  the only change needed is adding the PID to `udev/99-skullcandy.rules`.
- If you get nothing, the model likely uses different report ids or answers on
  the interrupt IN endpoint — capture the real traffic (next step).

### 3. Capture what the real app sends (logging shim)
Build and install the logger as `hid.dll`, then run Skull-HQ (under Wine here, or
on real Windows alongside the app — same DLL):
```bash
x86_64-w64-mingw32-gcc -O2 -shared -o tools/hidlog.dll tools/hidlog.c dll/hid.def -lkernel32
AIROHA="$(bash -c '. scripts/00-common.sh; find_airoha_dir')"
cp /usr/lib/wine/x86_64-windows/hid.dll "$AIROHA/hidwine.dll"
cp tools/hidlog.dll                      "$AIROHA/hid.dll"
WINEPREFIX=~/.wine-skullhq WINEDLLOVERRIDES="hid=n,b" \
  wine "$AIROHA"/../../../../../Skull-HQ.exe          # or use the launcher
tail -f /tmp/hid-shim.log
```
You’ll see every `HidD_SetOutputReport` / `HidD_GetInputReport` /
`HidD_GetFeature` with payloads and return codes. That tells you the report ids,
sizes, and which call carries the response.

### 4. Adjust the bridge if needed
`dll/hidbridge_dll.c` decides, per Skullcandy handle, how to service report I/O.
The helper (`bridge/hidbridge.py`) already supports four ops:

| op | meaning      | hidraw action        |
|----|--------------|----------------------|
| 1  | WRITE        | `write()`            |
| 2  | GETFEATURE   | `HIDIOCGFEATURE`     |
| 3  | SETFEATURE   | `HIDIOCSFEATURE`     |
| 4  | READ         | interrupt IN `read()`|

Typical change for a model that answers on interrupt IN: make
`HidD_GetInputReport` call `bridge_getfeature` → a new `bridge_read` that sends
op 4 instead of op 2. Rebuild with `scripts/build_dll.sh`.

### 5. Verify end-to-end
```bash
~/.local/share/skullcandy-hq/launch-skullhq.sh --enable-logging 2>&1 \
  | grep -E "type: '(DEVICE_INFO|BATTERY_INFO)'"
```
Success looks like `deviceName`, `batteryLevel`, EQ, etc. arriving.

### 6. Open a PR
Include: model name, `VID:PID`, the `hidprobe.py` output, and any
`hidbridge_dll.c` changes. Add the PID to `udev/99-skullcandy.rules`. If the
transport differed, add a short note to `docs/PROTOCOL.md`.

## Coding notes
- Keep `patch_asar.py` **anchored and reversible**; never use `asar pack` (it
  drops the `*.unpacked` native-module links and breaks the app). The in-place
  byte patch preserves offsets + integrity hashes that Electron verifies.
- The shim must stay a faithful drop-in for `hid.dll`: forward everything you
  don’t explicitly handle. Only Skullcandy-VID handles should be diverted.
- Prefer system Wine; document anything Wine-version specific.

## Quick checks before pushing
```bash
python3 -m py_compile scripts/patch_asar.py bridge/hidbridge.py tools/hidprobe.py
bash -n install.sh uninstall.sh scripts/*.sh
bash scripts/build_dll.sh        # DLL still builds
```
