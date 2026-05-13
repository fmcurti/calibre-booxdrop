# Calibre BooxDrop Plugin

A Calibre device plugin for sending books to BOOX e-readers over a local
network using BooxDrop.

## Overview

This plugin makes a BOOX device appear as a wireless device in Calibre
whenever BooxDrop is enabled on it. Books are streamed in chunks to the
BOOX device's HTTP API with per-byte progress reporting and a pre-flight
free-space check.

## Current limitations

- **Local network only.** Calibre and the BOOX device must be on the
  same LAN. There is no cloud/relay path.
- **One-way send.** `books()` returns an empty list, so Calibre doesn't
  know what's already on the device, and `delete_books` / `get_file`
  are not implemented yet. These require BooxDrop-side list/delete/
  download endpoints that are not currently available.

## Installation

### Released ZIP (when available)

1. Download `booxdrop-<version>.zip` from
   [GitHub Releases](https://github.com/fmcurti/calibre-booxdrop/releases).
2. In Calibre: Preferences → Plugins → Load plugin from file → pick the
   ZIP.
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

1. Enable BooxDrop on the BOOX device (Apps → BooxDrop).
2. In Calibre: Preferences → Plugins → BooxDrop Device → set the URL
   shown on the BOOX BooxDrop screen (e.g. `http://192.168.0.20:8085`).
3. The BOOX appears in Calibre's device toolbar; Send to Device works
   as with any other device.
