# Development and migration

## Preserve the existing installation

`maintenance/ha_tion_btle` starts at repository commit `a333d29570b6e1c4a2e430fd5c8ceb66213ae529`. It contains the old `custom_components/ha_tion_btle` directory and merged native Boost/recovery changes. This commit is the immutable source reference; deployed files have not been compared with it.

Use this branch for any deliberate updates to the existing private installation. Development of Tion Breezer 2026 uses a separate branch/PR. Repository edits, branch creation and PRs do not change files installed in Home Assistant.

Private repositories cannot be installed through HACS. Continue manual installation from an explicitly chosen commit. Publication and releases are separate follow-up work.

## Planned new installation

The new integration will use `custom_components/tion_breezer_2026` and the display name **Tion Breezer 2026**. It will not modify or import old `ha_tion_btle` config entries. Device identifiers and custom actions will use the new domain; entity registry entries will belong to the new integration.

Before testing it on one breezer:

1. Back up Home Assistant and record the old device's options and automation/entity references.
2. Install the new directory alongside the old directory and restart Home Assistant.
3. Disable the old integration entry for that breezer and confirm its connection has closed.
4. Add **Tion Breezer 2026** and configure only that breezer. Close any other BLE controller connection while pairing/testing.
5. Verify controls, Boost expiry, reload/restart and recovery after a device power cycle.
6. Map the new entities and actions explicitly in automations. Entity IDs, device IDs and history are not automatically transferred; matching friendly names can produce suffixed entity IDs.

Keep the other breezers on the old integration. For rollback, disable the new entry before re-enabling the old entry. Do not edit Home Assistant's internal registry files or run both integrations against the same breezer.

## Release prerequisites still pending

- Record the exact currently tested Home Assistant Core version and set the new HACS minimum to that baseline.
- Validate the renamed integration in Home Assistant and on hardware.
- Add brand assets, HACS validation and release infrastructure.
- Make the repository public only as a separate publication action.
