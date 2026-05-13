# Calibre BooxDrop Plugin

A Calibre device plugin for sending books between Calibre and a BOOX
e-reader over a local network using the BOOX-built-in BooxDrop service.

The BOOX appears as a wireless device in Calibre whenever BooxDrop is
enabled on it. Streaming chunked uploads with per-byte progress, a real
on-device library view with covers, delete-from-device, and
get-books-from-device are all supported.

## Installation

> [!IMPORTANT]
> Download from the **Releases** page, not the green **Code → Download
> ZIP** button at the top of this repository. The "Code" download wraps
> everything in a `calibre-booxdrop-main/` folder, and Calibre rejects it
> with "It does not contain a top-level `__init__.py` file." The release
> ZIP is structured correctly.

1. Download the latest `booxdrop-X.Y.Z.zip` asset from
   **[Releases → latest](https://github.com/fmcurti/calibre-booxdrop/releases/latest)**
   (the file named `booxdrop-X.Y.Z.zip`, not "Source code (zip)").
2. In Calibre: **Preferences → Plugins → Load plugin from file** → pick
   the ZIP.
3. Restart Calibre.

### Build from source

```bash
git clone https://github.com/fmcurti/calibre-booxdrop
cd calibre-booxdrop
make zip                 # produces booxdrop-<version>.zip
make install             # or: calibre-customize -a booxdrop-<version>.zip
```

### Live development

```bash
make dev-install         # equivalent to:
                         #   calibre-debug -s
                         #   calibre-customize -b .
calibre --debug-device-driver
```

## Usage

1. Enable BooxDrop on the BOOX device (Apps → BooxDrop). It displays a
   URL like `http://192.168.0.13:8085`.
2. In Calibre: **Preferences → Plugins → BooxDrop Device → Customize
   plugin**.
3. Click **Discover** to scan the LAN automatically, or paste the URL
   manually and click **Test**.
4. OK out — the BOOX should appear in Calibre's device toolbar within a
   few seconds.

Send books with the normal Send to Device action. The on-device pane
shows real titles, authors and covers pulled from BOOX's library.

## Current limitations

- **Local network only.** Calibre and the BOOX must be on the same LAN.
  There is no cloud/relay path.
- **Filename collisions.** BooxDrop renames clashing uploads (`Book.epub`
  → `Book_1.epub`); the plugin doesn't read the rename back, so
  re-sending an existing book may leave a stale entry in the device pane
  until you reconnect.
- **Single subnet.** The Discover scan only covers the primary outbound
  /24 — multi-NIC setups (Wi-Fi + Ethernet, VPN) need the URL set
  manually.
