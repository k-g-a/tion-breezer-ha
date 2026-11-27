# Project scope and differences

[Русский](project-scope.ru.md)

## Identity and compatibility

Tion Breezer 2026 is an independently maintained Home Assistant custom integration derived from [TionAPI/HA-tion](https://github.com/TionAPI/HA-tion). Its permanent domain is `tion_breezer_2026`. It is not an official Tion product or an in-place update to HA-tion.

The supported minimum is Core 2025.6.0. On Core 2025.6 the climate entity exposes legacy temperature properties. On Core 2026.11 it uses native temperature attributes. The maintainer reports four stable 4S devices under the previous integration domain on Core 2026.11.2.

## Changes relative to the original code used by this project

The comparison concerns the imported HA-tion source at `7f41b890b2241f8541a23e13bb71093632d6109f` and this project's subsequent changes. It is not a claim about the latest upstream release.

| Area | This project's implementation and trade-off |
| --- | --- |
| BLE lifecycle | Persistent connection per configured breezer, serialized polling and commands, HA BLEDevice refresh, retry connector, cleanup on unload and reconnect. Each breezer consumes a connection slot. |
| Packet recovery | Idempotent notification subscriptions, stale callback rejection, bounded handling of duplicated 4S fragments, with frame length and CRC validation retained. |
| Device power-cycle recovery | Stale backend cleanup and reconnect backoff capped at 60 seconds. |
| 4S Boost | Native firmware timer, configurable duration, remaining-time sensor and synchronized fan/climate state. Countdown continues without HA connectivity. |
| Away and Sleep | HA-managed convenience presets retained; native Boost temporarily overlays them. S3/Lite retain simulated Boost. |
| Fault handling | EC/WS codes remain visible. Device firmware accepts or rejects commands; rejected changes and unsuccessful error resets are reported. |
| Valve transitions | Power and outside/recirculation transitions share a 15-second settling window and expose remaining time. |
| 4S controls | Sound/light switches, filter/error reset buttons, operating counters, heater and temperature diagnostics, filter and device problem states. |
| Distribution | Protocol library bundled with the integration; no separately published tion-btle package required. Original license boundaries and attribution retained. |
| New identity | Independent directory, configuration domain, service namespace and device identifiers; migration is opt-in. |

## Tested scope and limitations

- Tion 4S is the primary hardware target: four units have been used in the maintainer's setup, including firmware 02D0 and 04C7. This is historical hardware experience, not certification of the renamed build.
- S3 and Lite code remains available, but equivalent hardware validation of this project is not established.
- Bluetooth proxy support is not claimed as hardware-verified. Adapter range and available connection slots affect operation.
- Only one integration/controller should maintain the BLE connection to a given breezer during testing.
- Automated protocol tests do not establish full Home Assistant lifecycle or hardware compatibility.

## Attribution

The integration remains Apache-2.0; the vendored BLE library remains LGPL-3.0-or-later. See [NOTICE.md](../NOTICE.md) for source revisions, authors and contributions. Original authorship is retained regardless of the new display name.
