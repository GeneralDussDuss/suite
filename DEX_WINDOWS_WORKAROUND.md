# Samsung DeX on Windows — The Workaround Guide

Samsung killed DeX for PC with One UI 6.0 (late 2023). No more running DeX in a window on your computer via USB. They want you to use Microsoft Phone Link instead. We don't want that. Here's how to get DeX back — and arguably better than before.

---

## TL;DR — Use scrcpy + ADB

**scrcpy** (open-source, free) can mirror your phone AND force actual DeX desktop mode on your PC. Lower latency than the old official app. Full keyboard/mouse/clipboard/audio/file support.

---

## Setup: scrcpy + DeX Mode

### Prerequisites

- Samsung Galaxy phone with DeX support
- USB-C cable (for initial setup; wireless after)
- Windows 10/11

### Step 1: Enable Developer Options & USB Debugging

1. **Settings > About Phone > Software Information** — tap **Build Number** 7 times
2. **Settings > Developer Options** — enable **USB Debugging**

### Step 2: Install scrcpy

```powershell
# Option A: winget (recommended)
winget install Genymobile.scrcpy

# Option B: Download from GitHub
# https://github.com/Genymobile/scrcpy/releases
# Extract the zip, ADB is bundled
```

### Step 3: Connect & Verify

```bash
# Plug in your phone via USB, accept the debugging prompt on the phone
adb devices
# Should show your device listed
```

### Step 4: Force DeX Mode

```bash
# Tell Android to use desktop mode on external displays
adb shell settings put global force_desktop_mode_on_external_displays 1

# Enable freeform windows (enhances the DeX experience)
adb shell settings put global enable_freeform_support 1
```

### Step 5: Launch scrcpy with DeX

```bash
# Launch a virtual display with DeX at 1080p
scrcpy --new-display=1920x1080/240 --turn-screen-off --stay-awake --video-bit-rate=16M --max-fps=60
```

**What those flags do:**
| Flag | Purpose |
|---|---|
| `--new-display=1920x1080/240` | Creates a virtual display at 1080p, 240 DPI — triggers DeX |
| `--turn-screen-off` | Turns off the phone screen to save battery |
| `--stay-awake` | Prevents phone from sleeping while connected |
| `--video-bit-rate=16M` | High quality video stream |
| `--max-fps=60` | Smooth 60fps |

You should see the full DeX desktop — taskbar, resizable windows, the whole thing.

### Step 6: Go Wireless (Optional)

After the initial USB setup:

```bash
# Switch ADB to TCP mode
adb tcpip 5555

# Disconnect USB cable, then connect wirelessly
adb connect <YOUR_PHONE_IP>:5555

# Launch scrcpy as before (same flags work)
scrcpy --new-display=1920x1080/240 --turn-screen-off --stay-awake --video-bit-rate=8M --max-fps=60
```

> **Tip:** Lower the bitrate to `8M` for wireless to reduce latency. Find your phone's IP at **Settings > About Phone > Status > IP Address**.

---

## Useful ADB Commands

```bash
# Disable DeX mode (revert to normal)
adb shell settings put global force_desktop_mode_on_external_displays 0

# Change DPI (if DeX UI elements are too big/small)
adb shell wm density 240        # lower = more space, higher = bigger UI
adb shell wm density reset      # back to default

# Keep phone awake while plugged in
adb shell settings put global stay_on_while_plugged_in 3

# List display IDs (useful for targeting DeX display)
adb shell dumpsys display | grep "Display Id"

# Mirror a specific display by ID
scrcpy --display-id=2

# Adjust mouse pointer speed
adb shell settings put system pointer_speed 7

# Alternative DeX toggle (broadcast method)
adb shell am broadcast -a com.samsung.android.desktopmode.action.CHANGE_MODE --ei mode 1
```

---

## Quick Launch Script

Save this as `dex.bat` on your desktop:

```batch
@echo off
echo Starting Samsung DeX via scrcpy...
adb shell settings put global force_desktop_mode_on_external_displays 1
adb shell settings put global enable_freeform_support 1
timeout /t 2 /nobreak >nul
scrcpy --new-display=1920x1080/240 --turn-screen-off --stay-awake --video-bit-rate=16M --max-fps=60 --power-off-on-close
```

Or for wireless (`dex-wireless.bat`):

```batch
@echo off
echo Connecting wirelessly...
adb connect %1:5555
timeout /t 2 /nobreak >nul
echo Starting Samsung DeX via scrcpy...
adb shell settings put global force_desktop_mode_on_external_displays 1
scrcpy --new-display=1920x1080/240 --turn-screen-off --stay-awake --video-bit-rate=8M --max-fps=60 --power-off-on-close
```

Usage: `dex-wireless.bat 192.168.1.42`

---

## Alternative Methods (Compared)

| Method | Actual DeX? | Latency | Free? | KB/Mouse from PC? | Best For |
|---|---|---|---|---|---|
| **scrcpy + ADB** | Yes | Excellent | Yes | Yes | Full DeX replacement (recommended) |
| **Wireless DeX (Miracast)** | Yes | Poor (100-300ms) | Yes | No (need BT peripherals) | Quick cast to a TV/monitor |
| **Phone Link (App Streaming)** | No | Decent | Yes | Yes | Running individual Android apps |
| **Vysor Pro** | No (without ADB) | Good | $10/yr | Yes | GUI alternative to scrcpy |
| **Samsung Flow** | No | Poor | Yes | Limited | Notification sync only |

**Wireless DeX via Miracast** is built into Samsung phones and Windows (install "Wireless Display" optional feature in Windows Settings > Apps > Optional Features). But you can't use your PC keyboard/mouse without workarounds, and the latency is rough. Only use this if you're casting to a TV or secondary display.

**Phone Link** is fine for texting from your PC and running a single app. It's not DeX.

---

## Troubleshooting

**"DeX doesn't activate, just shows normal phone screen"**
- Make sure the ADB command ran: `adb shell settings get global force_desktop_mode_on_external_displays` should return `1`
- Try the broadcast method: `adb shell am broadcast -a com.samsung.android.desktopmode.action.CHANGE_MODE --ei mode 1`
- Try `scrcpy --display-id=2` after triggering DeX
- Restart scrcpy after running the ADB commands

**"scrcpy connects but shows nothing / black screen"**
- Revoke and re-authorize USB debugging on the phone
- Try: `adb kill-server && adb start-server && adb devices`
- Update scrcpy to latest version (need v3.0+ for `--new-display`)

**"Wireless connection drops"**
- Ensure phone and PC are on the same Wi-Fi network (ideally 5GHz)
- Re-pair: `adb disconnect && adb connect <IP>:5555`
- If persistent, switch to USB — it's always more stable

**"Audio not forwarding"**
- Audio forwarding requires scrcpy 2.0+. Add `--audio-codec=opus` for better audio quality.
- Some Samsung phones need: `adb shell appops set com.genymobile.scrcpy PROJECT_MEDIA allow`

**"Lag/stuttering over wireless"**
- Lower bitrate: `--video-bit-rate=4M`
- Lower resolution: `--new-display=1280x720/240`
- Lower fps: `--max-fps=30`
- Move closer to your Wi-Fi router or use 5GHz band

---

## Why scrcpy > Old DeX for PC

- **Lower latency** — especially over USB, scrcpy is faster than the old Samsung app
- **Higher resolution/fps** — configurable up to your phone's max capability
- **Audio forwarding** — the old DeX for PC didn't do this well
- **Open source** — no Samsung deprecation risk, community-maintained
- **Cross-platform** — works on Windows, macOS, and Linux
- **Phone screen off** — saves battery, old app kept the phone screen on
- **File drag-and-drop** — works in both directions

Samsung did us dirty by killing the app, but honestly scrcpy is the better tool. The only thing lost is the one-click convenience, and that's what the batch scripts above solve.
