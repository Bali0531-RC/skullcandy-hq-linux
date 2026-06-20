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

## Install via Lutris (optional)

Prefer to manage it from Lutris? There are two flavours, both using the same
machinery (system Wine + native HID bridge) via the built-in **linux** runner.

### A) From your local clone

Generates an installer that calls *this* checkout's `install.sh`:

```bash
./scripts/make_lutris_script.sh          # writes ./skullcandy-hq.lutris.yaml
lutris --install ./skullcandy-hq.lutris.yaml
```

The generated YAML hard-codes the path to this clone, so keep the repo in place
(re-run `make_lutris_script.sh` if you move it).

### B) Plug-and-play (publishable)

`lutris/skullcandy-hq.publish.yaml` is fully self-contained — every input comes
from a URL (it downloads the Skull-HQ installer **and** this repo's tarball from
GitHub), so it can be shared or submitted to the Lutris website and installed by
anyone:

```bash
lutris --install ./lutris/skullcandy-hq.publish.yaml
```

> Publishing it requires this repo to be pushed to GitHub (it pulls
> `…/archive/refs/heads/main.tar.gz`). For a reproducible published installer, cut
> a release tag and point the `bridge` file at `…/refs/tags/vX.Y.Z.tar.gz` instead
> of `main`. Lutris-website submissions are reviewed by moderators; an installer
> that runs a downloaded `install.sh` and needs a manual `sudo` for udev may or
> may not be accepted there — it always works when installed from the file directly.

### Both flavours

- They auto-download the official **Skull-HQ 3.2.0** installer (the version the
  asar patcher is anchored to); you can still override with a local `.exe` in the
  download dialog.
- They drive your **system Wine** through the project's own launcher — there's no
  Wine-version picker. Proton/GE-Proton can't do the headset HID, which is why
  Lutris doesn't manage Wine here.
- The **udev rule needs root**, which Lutris can't do mid-install. If the headset
  shows up as “no device”, install it once (the command is shown in the Lutris
  install notes) and re-plug:
  ```bash
  sudo cp ./udev/99-skullcandy.rules /etc/udev/rules.d/99-skullcandy.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger
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
  make_lutris_script.sh    render the Lutris installer from the template
bridge/
  hidbridge.py             native Linux HID helper daemon (TCP 127.0.0.1:38099)
dll/
  hidbridge_dll.c          the hid.dll shim source
  hid.def                  export list (forwards 39 fns to Wine, wraps 5)
  hid_bridge.dll           prebuilt x86_64 shim
systemd/hidbridge.service  user service for the helper
udev/99-skullcandy.rules   device permissions
launcher/ , desktop/       templates rendered at install time
lutris/                    skullcandy-hq.yaml.in (local template) +
                           skullcandy-hq.publish.yaml (self-contained, publishable)
tools/                     hidprobe.py (native probe) + hidlog.c (traffic logger)
docs/PROTOCOL.md           captured Airoha protocol notes
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
- **Black/laggy window or “This application could not be started” (GPU).** The
  launcher defaults to ANGLE-on-Vulkan (`--use-angle=vulkan`), which is far more
  reliable under Wine than the GL/EGL path — especially on NVIDIA/hybrid laptops,
  where you'd otherwise see `libEGL … failed to create dri2 screen` and a GPU
  process crash. To change it, set `SKULLHQ_ANGLE` before launching:
  `SKULLHQ_ANGLE=gl` (desktop GL), `SKULLHQ_ANGLE=d3d11`, or `SKULLHQ_ANGLE=`
  (empty) to disable and fall back to software with `--disable-gpu`. In Lutris,
  set these under the game's **System options → Environment variables**.
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

## Extending to other models / hacking

The bridge is byte-transparent and filters by Skullcandy **vendor** id, so other
Airoha-based Skullcandy headsets are likely to work as-is. To check yours and
contribute support:

- `docs/PROTOCOL.md` — the captured Airoha control protocol (transport, a decoded
  `AB1565` command/response, why Wine needs the bridge).
- `CONTRIBUTING.md` — step-by-step capture-and-verify workflow.
- `tools/hidprobe.py` — native probe; lists your device and exercises the
  control protocol with no Wine involved:
  ```bash
  ./tools/hidprobe.py
  ./tools/hidprobe.py --send 060a00055a06000c0a0210e803 --get 0x07   # AB1565 info
  ```
- `tools/hidlog.c` — a logging pass-through `hid.dll` to capture exactly what the
  app sends/receives for a new model.

---

## Legal

Independent, unofficial project. Contains **no** Skullcandy software. The asar
patch only edits your own local install at install time and is fully reversible
(`scripts/patch_asar.py --revert`). “Skullcandy”, “Skull-HQ”, “SLYR” are
trademarks of their respective owners. MIT licensed (see `LICENSE`).
