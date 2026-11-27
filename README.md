# Tion Breezer 2026 for Home Assistant

[Русский](README.ru.md)

Control Tion 3S, 4S and Lite breezers over Bluetooth. The protocol library is included. This independently maintained integration targets **Home Assistant Core 2025.6.0 and later**. The maintainer runs four stable 4S units on Core 2026.11.2 with the previous domain. All four required manual pairing with `bluetoothctl`. See the [Bluetooth guide](docs/bluetooth.md) and [hardware coverage](docs/project-scope.md).

## Current branch

The component in this documentation branch still uses `ha_tion_btle`. For that installation, copy `custom_components/ha_tion_btle` from the [maintenance branch](https://github.com/k-g-a/tion-breezer-ha/tree/maintenance/ha_tion_btle) into `/config/custom_components/` and restart Core. Its entries keep their existing domain. The independent release described below is prepared in [PR #13](https://github.com/k-g-a/tion-breezer-ha/pull/13).

## Installation

For an existing installation under `ha_tion_btle`, see [Migrate without re-adding devices](docs/development-and-migration.md) before configuring any new entries.

Once the independent release is public, open the [repository in Home Assistant](https://my.home-assistant.io/redirect/hacs_repository/?owner=k-g-a&repository=tion-breezer-ha&category=integration). On Core 2025.6–2026.10 this opens HACS (install HACS first). On Core 2026.11+ it opens **Settings → Marketplace**. Add the repository as an **Integration**, download it and follow the restart prompt. Custom repositories require a GitHub connection. Catalog approval is separate.

For manual installation from the independent release, copy `custom_components/tion_breezer_2026` into `/config/custom_components/` and restart Core. For a new device, open **Settings → Devices & services → Add integration → Tion Breezer 2026**. If you paired on the host, clear **Need pair**.

## Bluetooth behavior

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

## Prior work and provenance

This project is derived from:

- [`TionAPI/HA-tion`](https://github.com/TionAPI/HA-tion), primarily authored and maintained by [Igor Tkachenko (`@IATkachenko`)](https://github.com/IATkachenko), at commit `7f41b890b2241f8541a23e13bb71093632d6109f`;
- [`TionAPI/tion_python`](https://github.com/TionAPI/tion_python), also primarily authored by Igor Tkachenko;
- the BLE reliability analysis and embedded-library prototype contributed by [`@tms320`](https://github.com/tms320) in [`TionAPI/HA-tion#154`](https://github.com/TionAPI/HA-tion/issues/154);
- the connection-layer fixes merged in [`k-g-a/tion_python#1`](https://github.com/k-g-a/tion_python/pull/1), vendored from commit `cf940bc21de629bf652762065b8466c39cdb0280`.

See [NOTICE.md](NOTICE.md) for licensing boundaries and detailed attribution.

## Licence

The Home Assistant integration code remains under Apache License 2.0. The vendored `tion_btle` library remains under GNU LGPL 3.0 or later. The applicable licence is included with each part of the codebase.
