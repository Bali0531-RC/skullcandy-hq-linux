# Skullcandy HQ on Linux (SLYR Pro) — Wine + native HID bridge

Run the Windows **Skull-HQ** app under Wine on Linux and get **full control of a
USB-connected Skullcandy SLYR Pro** — device info, battery, EQ, sidetone,
game/chat mix, mic volume, Mimi/spatial audio, etc.

This is an automated installer, not a redistributable bundle: it builds a
dedicated Wine prefix on your machine, installs Skull-HQ from the official
installer **you provide**, patches it for Linux device detection, and installs a
small native **HID bridge** that makes the headset's control protocol work under
Wine.

> Status: **working** on Skull-HQ 3.2.0, SLYR Pro (VID `34f0` PID `2220`),
> CachyOS/Arch with **system Wine 11.x**. Other Skullcandy Airoha headsets very
> likely work (the bridge is vendor-generic) but are untested — see *Caveats*.

---

## Why a bridge is needed

The Airoha SDK inside Skull-HQ (`AirohaHidCoreLib.dll`) talks to the headset
using Windows HID **control-pipe** reports (`HidD_SetOutputReport` /
`HidD_GetInputReport`). Under Wine those GET_REPORT calls come back empty, so the
app connects but never receives any data.

The headset actually replies on the control-pipe **FEATURE** report, which the
Linux kernel exposes via the `HIDIOCGFEATURE` ioctl on `/dev/hidrawN`. Wine can't
issue that ioctl — but a tiny native helper can. So:

```
 Skull-HQ (Electron, Wine)
   └─ AirohaHidCoreLib.dll
        └─ hid.dll  ← our shim (replaces Wine's, forwards everything else)
             │  Skullcandy report I/O only
             ▼
        Winsock TCP 127.0.0.1:38099
             ▼
        hidbridge.py (native Linux helper)
             ▼
        /dev/hidraw0  (write output report, HIDIOCGFEATURE for the reply)
```

A second small patch makes the app **detect** the headset: under Wine
`node-hid` returns nothing, so `headset.service.js` falls back to reading USB
descriptors straight from `/dev/bus/usb` (via Wine's `Z:` drive).

---

## Requirements

- **System Wine** (not Proton/GE-Proton — those have weaker HID and won't work).
  Tested with Wine 11.x. `winetricks` too.
- `python3`
- `mingw-w64-gcc` *(optional)* — to rebuild the bridge DLL from source. A prebuilt
  `dll/hid_bridge.dll` (x86_64) is included, so this is optional.
- The official **Skull-HQ installer** (download it yourself from Skullcandy).
- A Skullcandy SLYR Pro (or other Airoha-based Skullcandy headset) on **USB**.

Arch/CachyOS:
```bash
sudo pacman -S wine winetricks python mingw-w64-gcc
```

---

## Install

```bash
git clone <this-repo> skullcandy-hq-linux
cd skullcandy-hq-linux
./install.sh --installer /path/to/Skull-HQ-Setup.exe
```

If Skull-HQ is already installed in the prefix, just `./install.sh`.

What it does (all idempotent):
1. creates a Wine prefix at `~/.wine-skullhq` and installs `vcrun2022` + `dotnet48`
2. runs the Skull-HQ installer
3. patches `resources/app.asar` for Linux detection (reversible; keeps a `.bak`)
4. builds/installs the bridge `hid.dll` next to `AirohaHidCoreLib.dll`
5. installs the `hidbridge` helper as an enabled **user** service (auto-starts on login)
6. installs the udev rule, launcher, and a desktop entry

Then launch **“Skullcandy HQ (SLYR Pro)”** from your app menu, or:
```bash
~/.local/share/skullcandy-hq/launch-skullhq.sh
```

---

## How it’s laid out

```
install.sh                 one-command installer
uninstall.sh               clean removal (--purge-prefix to also delete the prefix)
scripts/
  00-common.sh             shared paths/helpers
  patch_asar.py            byte-level, integrity-safe asar patcher (reversible)
  build_dll.sh             build hid_bridge.dll with mingw
bridge/
  hidbridge.py             native Linux HID helper daemon (TCP 127.0.0.1:38099)
dll/
  hidbridge_dll.c          the hid.dll shim source
  hid.def                  export list (forwards 39 fns to Wine, wraps 5)
  hid_bridge.dll           prebuilt x86_64 shim
systemd/hidbridge.service  user service for the helper
udev/99-skullcandy.rules   device permissions
launcher/ , desktop/       templates rendered at install time
```

### The bridge `hid.dll`
Exports all 44 functions of Wine’s `hid.dll`. 39 are **forwarders** straight to
the real Wine HID (shipped renamed as `hidwine.dll`). Only the report-I/O
functions are wrapped: for handles whose VID is Skullcandy (`0x34F0`) it routes
`HidD_SetOutputReport`→helper *write* and `HidD_GetInputReport`/`HidD_GetFeature`
→helper *HIDIOCGFEATURE*. Everything non-Skullcandy is untouched.

---

## Troubleshooting

- **App opens but shows “no device”.** Make sure it’s on **USB** (not Bluetooth),
  the helper is running (`systemctl --user status hidbridge`), and the device
  node is accessible (`ls -l /dev/hidraw*` should be `rw` for all). Re-plug to
  trigger the udev rule.
- **Helper says “device NOT FOUND”.** Check `lsusb | grep 34f0`. If present but
  permission-denied, the udev rule didn’t apply — re-run the udev step in
  `install.sh` or `sudo udevadm trigger`.
- **You’re using Proton/GE-Proton.** Don’t — the launcher uses system Wine on
  purpose. Proton’s Wine 10.x couldn’t do the HID GET_REPORT.
- **No window on Wayland.** The app runs via XWayland and shows normally; some
  tools just can’t enumerate the window. Check `pgrep -af Skull-HQ.exe`.
- **Verbose HID/Airoha logs.** Run the launcher with `--enable-logging` and watch
  for `type: 'DEVICE_INFO'`, `BATTERY_INFO`, etc.

---

## Caveats / honesty

- **Not a prebuilt bundle.** Legally we can’t ship Skull-HQ or a Wine prefix
  containing it; technically a prefix isn’t portable. So it’s an installer.
- **Tested only on SLYR Pro** (the protocol response containing `AB1565` — the
  Airoha chip — was verified). The detection patch and the bridge filter by
  Skullcandy **vendor** id, so other Airoha Skullcandy models should work, but
  this is unverified. For a different model, set `SKDY_PRODUCT` for the udev rule
  and (optionally) `HIDBRIDGE_PRODUCT` for the helper.
- **App updates** may rewrite `app.asar`; just re-run `./install.sh`. The patcher
  is version-anchored and will refuse cleanly if Skullcandy changes that file too
  much.
- **GPU/Wayland rendering** quality depends on your Wine/driver setup; the headset
  control path is independent of the GUI rendering.

---

## Uninstall

```bash
./uninstall.sh              # remove integration, keep the prefix/app
./uninstall.sh --purge-prefix   # also delete ~/.wine-skullhq
```

---

## Legal

Independent, unofficial project. Contains **no** Skullcandy software. The asar
patch only edits your own local install at install time and is fully reversible
(`scripts/patch_asar.py --revert`). “Skullcandy”, “Skull-HQ”, “SLYR” are
trademarks of their respective owners. MIT licensed (see `LICENSE`).
