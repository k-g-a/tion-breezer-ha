# Notices and provenance

This repository combines two previously separate projects while retaining their original licensing boundaries.

## Home Assistant integration

`custom_components/ha_tion_btle`, excluding its `tion_btle` subdirectory, is derived from `TionAPI/HA-tion` at commit `7f41b890b2241f8541a23e13bb71093632d6109f`.

Copyright belongs to the original contributors. The primary original author is Igor Tkachenko (`@IATkachenko`). This part is licensed under Apache License 2.0; see the root `LICENSE` file.

## Vendored Bluetooth library

`custom_components/ha_tion_btle/tion_btle` is derived from `TionAPI/tion_python`, including the reliability changes merged in `k-g-a/tion_python#1`, at commit `cf940bc21de629bf652762065b8466c39cdb0280`.

Copyright belongs to the original contributors. The primary original author is Igor Tkachenko (`@IATkachenko`). This part is licensed under GNU Lesser General Public License version 3 or later; see `custom_components/ha_tion_btle/tion_btle/LICENSE`.

## Additional prior work

The diagnosis, patch outline, and embedded-library prototype published by `@tms320` in `TionAPI/HA-tion#154` informed the integration-layer reliability changes, particularly shorter retry recovery, explicit cleanup, and removal of nested connection lifecycles.

Repository history and links:

- https://github.com/TionAPI/HA-tion
- https://github.com/TionAPI/tion_python
- https://github.com/TionAPI/HA-tion/issues/154
- https://github.com/k-g-a/tion_python/pull/1
