# Migrate an existing installation

[Русский](development-and-migration.ru.md)

For an existing installation of this fork under `ha_tion_btle`, the maintenance branch remains available. Installing the independent component alongside it does not import devices. For a fresh installation, follow the README. For configured breezers, the following optional offline migration keeps the existing entries, options, device IDs and entity IDs. It requires no pairing and no changes to BlueZ.

## Move all configured breezers together

This is an advanced, project-provided procedure for the renamed build. Home Assistant has no supported UI operation to rename a custom integration's domain. The tool works on copies of internal storage files. Check the result on a restored test backup if possible. Start with an installation that has **no entries or devices already configured under the new domain**.

1. Create and download a full HA backup. Keep the existing component and a copy of its version. Copy the new component into `/config/custom_components/tion_breezer_2026`. Do not add it through Devices & services yet.
2. Stop Core (`ha core stop` on HAOS). On the HAOS host via SSH port 22222, the config directory is normally `/mnt/data/supervisor/homeassistant`. From its `.storage` directory copy **core.config_entries**, **core.entity_registry** and **core.device_registry** into a private folder named `original` on a Linux machine with Python 3.10+. These files contain credentials for other integrations too. Keep Core stopped until all three files are in place.
3. From the renamed release checkout, run the following on the copies. The first command previews the counts. For a four-breezer installation expect four config entries. If ownership, conflicts or counts are unexpected, stop and restart Core with the originals.

   ```sh
   python3 tools/migrate_registries.py original
   python3 tools/migrate_registries.py original --output migrated
   ```

4. Inspect the differences locally. The expected changes are the config-entry domain, entity platform and Tion device identifier namespace (including matching deleted records). Preserve entry IDs, device IDs, entity IDs, options, names and MACs. JSON formatting can differ. Copy the three migrated files back over their originals with the same ownership and permissions. If a copy fails, restore **all three originals before starting Core**.
5. Start Core (`ha core start`). Verify the four entries, their names/options, device pages, entity IDs, history, fan commands, climate and Boost. Check automations, scripts and dashboards for `ha_tion_btle.set_air_source` and change it to `tion_breezer_2026.set_air_source`. Update explicit integration-domain filters as well. Standard fan and climate actions can keep targeting the same IDs.
6. If verification fails, stop Core, put all three originals back together, restore the previous component and custom action references, then start Core. Use the full backup if other configuration has changed since the snapshot. Keep only one integration controlling each breezer.

The offline conversion was exercised on fixture data. Live verification of the renamed build and your own registry snapshot is still required.
