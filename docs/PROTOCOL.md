# Airoha HID protocol notes (SLYR Pro)

These are the concrete things learned while making the SLYR Pro work under Wine.
They should let you extend support to other Skullcandy (Airoha) headsets. Where
something is inferred from a single captured exchange rather than verified, it’s
marked **(inferred)**.

## The device

- Skullcandy SLYR Pro, USB `VID 0x34F0 / PID 0x2220`.
- Airoha **AB1565** SoC (the chip name comes back verbatim in a response — see
  below).
- The control interface is USB interface **MI_05**, which exposes two HID
  top-level collections:

  | collection | usage page | usage  | role                                  |
  |-----------:|:----------:|:------:|---------------------------------------|
  | col01      | `0x000C`   | `0x01` | Consumer Control (media keys)         |
  | **col02**  | `0xFF13`   | `0x01` | **vendor channel — Airoha control**   |

  All control traffic goes over **col02** (`usage_page 0xFF13`). On Linux the
  whole MI_05 interface is one node, `/dev/hidrawN`.

## Transport (the important part)

The Airoha SDK uses HID **control-pipe reports**, not the interrupt endpoints:

| direction | what            | Windows call            | Linux hidraw            |
|-----------|-----------------|-------------------------|-------------------------|
| host→dev  | command         | `HidD_SetOutputReport`  | `write()`               |
| dev→host  | response        | `HidD_GetInputReport`*  | `HIDIOCGFEATURE` ioctl  |

\* The app polls with `HidD_GetInputReport`, but the data actually lives in the
**FEATURE** report. On real Windows that distinction is hidden; on Linux you must
use `HIDIOCGFEATURE`. The interrupt IN endpoint (`read()`) returns **nothing**.

### Why it breaks under Wine
- `HidD_GetInputReport` → returns the report id followed by **all zeros**.
- `HidD_GetFeature`     → returns **FALSE** (`-1`).
- Native Linux `HIDIOCGFEATURE` on the same `/dev/hidrawN` → **returns the real
  data**.

That gap is the whole reason for the bridge: the Wine-side `hid.dll` shim routes
`SetOutputReport`/`GetInputReport` to a native helper that does `write()` +
`HIDIOCGFEATURE`.

## A captured exchange — "get device info"

Output report sent by the app (report id `0x06`, 62 bytes, zero-padded):

```
06 0a 00 05 5a 06 00 0c 0a 02 10 e8 03
```

FEATURE reply read with `HIDIOCGFEATURE`, report id `0x07` (63 bytes):

```
07 3b 00 05 5b 0d 00 0c 0a 00 02 10 06 00 41 42 31 35 36 35 ...
                                          └──────────────────┘
                                           ASCII "AB1565"
```

### Frame structure **(inferred from this one sample)**

```
off  bytes      meaning
 0   06 / 07    HID report id (06 = output/command, 07 = input/feature reply)
 1‑2 u16 LE     frame length after this field            (cmd 0x000a, rsp 0x003b)
 3   05         Airoha "RACE" channel id
 4   5A / 5B    5A = command (host→device), 5B = reply (device→host)
 5‑6 u16 LE     payload length                           (cmd 0x0006, rsp 0x000d)
 7‑8 u16 LE     command id                               (0x0A0C here)
 9   ..         reply: status byte (00 = OK); params follow
```

So `0x5A` requests and `0x5B` replies, with the command id echoed back. This
matches Airoha’s “RACE” command convention. Treat the field breakdown as a
starting point, not gospel — only this one command was decoded. Higher-level
fields (deviceName `"SLYR PRO"`, firmware `"0.0.1.49"`, battery, EQ, …) come from
additional commands the SDK issues; we never had to decode them because the
bridge is **byte-transparent** — it just shuttles whatever the SDK sends/expects.

## What this means for other models

Any Skullcandy Airoha headset that uses the same **{output report → FEATURE
reply}** transport will work through the existing bridge **without any protocol
changes** — the bridge filters by Skullcandy **vendor** id only and forwards raw
bytes. The things that can differ per model:

- **PID** (only matters for the udev rule; the bridge matches vendor `0x34F0`).
- **Report ids / sizes** (the bridge passes through whatever the app uses).
- **Transport** — if a model instead answers on the **interrupt IN** endpoint,
  switch that model’s response path from `GETFEATURE` (op 2) to `READ` (op 4) in
  `dll/hidbridge_dll.c`; the helper already implements op 4.

See `CONTRIBUTING.md` for the capture-and-verify workflow using `tools/`.
