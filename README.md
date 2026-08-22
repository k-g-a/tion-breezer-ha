# Tion Breezer for Home Assistant

A standalone custom integration for controlling Tion S3, S4, and Lite breezers over Bluetooth.

This project combines the Home Assistant integration and its Bluetooth protocol library in one repository. The library is vendored under `custom_components/ha_tion_btle/tion_btle`, so installation does not depend on a separately published `tion-btle` package.

## Status

The initial version is intended for local testing on Home Assistant 2025.6 or newer. It preserves the existing integration domain, `ha_tion_btle`, so existing config entries can continue to work after replacing the old custom component.

The BLE reliability changes include:

- Home Assistant-compatible connections through `bleak-retry-connector`;
- fresh `BLEDevice` data from Home Assistant for reconnects and Bluetooth proxies;
- one shared session queue for every configured Tion breezer;
- explicit notification shutdown and BlueZ disconnect confirmation;
- a five-second upper bound while waiting for protocol data;
- serialized polling and commands across all Tion breezers;
- removal of nested connect/disconnect calls in climate commands;
- a one-minute retry interval after a failed poll instead of ten minutes.

Connections are operation-scoped. A command or poll may reuse its connection for
multiple protocol frames, but teardown completes before the next Tion operation
is admitted. This experimental lifecycle avoids reserving one adapter slot per
breezer while preventing simultaneous scheduled polls from occupying all slots.

## Manual installation

Private GitHub repositories cannot be installed through HACS. Until this repository is made public:

1. Copy `custom_components/ha_tion_btle` from this repository to `/config/custom_components/ha_tion_btle` in Home Assistant.
2. Replace the whole existing directory if the original HA-tion integration is installed.
3. Restart Home Assistant.
4. Existing devices should remain configured because the integration domain is unchanged. For a new device, open **Settings → Devices & services → Add integration**, then search for **Tion Breezer**.

Do not copy the repository root into `custom_components`; copy the `ha_tion_btle` directory itself.

## Debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.ha_tion_btle: debug
    custom_components.ha_tion_btle.tion_btle.tion: debug
    custom_components.ha_tion_btle.tion_btle.s3: debug
    custom_components.ha_tion_btle.tion_btle.s4: debug
    custom_components.ha_tion_btle.tion_btle.lite: debug
```

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest
ruff check .
```

The repository already uses the HACS-compatible `custom_components/<domain>` layout and contains `hacs.json`. Before public HACS distribution, add brand assets, enable HACS validation, make the repository public, and optionally add a release workflow. Releases are deliberately not automated in this initial private version.

## Prior work and provenance

This project is derived from:

- [`TionAPI/HA-tion`](https://github.com/TionAPI/HA-tion), primarily authored and maintained by [Igor Tkachenko (`@IATkachenko`)](https://github.com/IATkachenko), at commit `7f41b890b2241f8541a23e13bb71093632d6109f`;
- [`TionAPI/tion_python`](https://github.com/TionAPI/tion_python), also primarily authored by Igor Tkachenko;
- the BLE reliability analysis and embedded-library prototype contributed by [`@tms320`](https://github.com/tms320) in [`TionAPI/HA-tion#154`](https://github.com/TionAPI/HA-tion/issues/154);
- the connection-layer fixes merged in [`k-g-a/tion_python#1`](https://github.com/k-g-a/tion_python/pull/1), vendored from commit `cf940bc21de629bf652762065b8466c39cdb0280`.

See [NOTICE.md](NOTICE.md) for licensing boundaries and detailed attribution.

## Licence

The Home Assistant integration code remains under Apache License 2.0. The vendored `tion_btle` library remains under GNU LGPL 3.0 or later. The applicable licence is included with each part of the codebase.
