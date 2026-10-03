# Tion Breezer for Home Assistant

A standalone custom integration for controlling Tion S3, S4, and Lite breezers over Bluetooth.

This project combines the Home Assistant integration and its Bluetooth protocol library in one repository. The library is vendored under `custom_components/ha_tion_btle/tion_btle`, so installation does not depend on a separately published `tion-btle` package.

## Status

This branch contains the existing private integration, domain `ha_tion_btle`.
Its source baseline is preserved on [`maintenance/ha_tion_btle`](https://github.com/k-g-a/tion-breezer-ha/tree/maintenance/ha_tion_btle) at commit `a333d29570b6e1c4a2e430fd5c8ceb66213ae529` (merged PR #11). This is a repository snapshot; the deployed files have not been independently compared with it.

The planned independent integration is **Tion Breezer 2026**, domain `tion_breezer_2026`. It will use its own directory and new configuration entries, with no automatic takeover of HA-tion devices. See [project scope and differences](docs/project-scope.md) and [development and migration](docs/development-and-migration.md).

The support baseline will be the maintainer's currently tested **Home Assistant Core** version. Its exact version is awaiting confirmation. The inherited `2025.6.0` HACS minimum is historical metadata, not a verified baseline for the new integration. No compatibility claim is made for other HA versions.

The BLE reliability changes include:

- Home Assistant-compatible connections through `bleak-retry-connector`;
- fresh `BLEDevice` data from Home Assistant for reconnects and Bluetooth proxies;
- cleanup after failed or unexpected connections;
- protected connection bookkeeping;
- a five-second upper bound while waiting for protocol data;
- serialized polling and commands per breezer;
- removal of nested connect/disconnect calls in climate commands;
- reconnect backoff capped at one minute;
- notification subscription cleanup and bounded duplicate-fragment handling with strict frame validation;
- recovery after breezer power cycles without requiring an HA restart.

The integration keeps one persistent BLE connection per configured breezer. This avoids the Home Assistant/BlueZ backend-selection failures observed after repeated 4S reconnects, at the cost of consuming one adapter connection slot per breezer.

## Tion 4S controls and diagnostics

In addition to power, fan, climate, and air-source controls, Tion 4S devices expose:

- persisted sound- and light-indication switches;
- filter-resource and device-error reset buttons;
- device-problem, filter-replacement, heater-activity, timer, and MagicAir binary states;
- controller and power-board temperatures;
- heater output and installed-heater rating;
- operating time, fan time, airflow counter, and calculated total airflow;
- maximum fan speed, communication source, and active EC/WS codes.

Device EC/WS errors remain visible. Commands are sent to the device even during an active fault; the firmware decides whether to accept them. A rejected state change is reported as an error rather than silent success. Reset Errors cannot clear a fault whose physical condition remains active. Power and air-source transitions share a 15-second valve-settling window.

Tion 4S Boost uses the breezer's native Turbo timer rather than a simulated maximum-speed preset. The device reports whether Turbo is active and how many seconds remain, restores its previous operating state when the timer expires, and continues the countdown without a Bluetooth connection. The duration defaults to five minutes and can be changed in the integration options. Fan and climate entities show the same device-reported Boost state; Away and Sleep remain Home Assistant-managed convenience presets.

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
