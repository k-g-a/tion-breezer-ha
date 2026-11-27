# Move existing breezers to Tion Breezer 2026

[Русский](development-and-migration.ru.md)

For installations of the original HA-tion integration or this fork with domain `ha_tion_btle`. The script moves all configured breezers together. Config-entry IDs, entity IDs, device IDs, names, options and Bluetooth bonds are preserved.

1. Download a Home Assistant backup. Install **Tion Breezer 2026** through HACS (Core 2025.6+) or **Settings → Marketplace** (Core 2026.11+). Leave the old integration installed and its entries in place. Skip the new-device setup screen.
2. Open **Terminal & SSH** on HAOS and run:

   ```sh
   sh /config/custom_components/tion_breezer_2026/migrate.sh
   ```

   If you use **HAOS host SSH on port 22222**, run this instead:

   ```sh
   sh /mnt/data/supervisor/homeassistant/custom_components/tion_breezer_2026/migrate.sh
   ```

   The script uses the HA CLI and jq. It stops Core, which releases the old integration's BLE connections, backs up the registries, converts them and starts Core again. Other integrations are briefly offline. The terminal prints the migrated entry count and private backup location. It refuses to combine existing new-domain entries with old ones.
3. Open **Settings → Devices & services → Tion Breezer 2026**. Check that your breezers are listed, readings update and a fan command works. An entry you disabled manually stays disabled until you enable it here. Existing automations can keep their entity IDs. Replace explicit `ha_tion_btle.set_air_source` actions with `tion_breezer_2026.set_air_source` and update any explicit domain filters.
4. After verification, uninstall the **old HA-tion package** in HACS/Marketplace, or remove only `custom_components/ha_tion_btle` if installed manually. Follow any restart prompt. Keep `custom_components/tion_breezer_2026` and the migrated entries.

## Recovery and other installations

If the script reports an interrupted registry replacement, rerun the same command with `--recover` to restore all three originals and restart Core. If an abruptly killed shell left a lock, first confirm the migration process has exited and follow the printed lock instruction. If Core stayed stopped before replacement started, start it with `ha core start`. To undo a completed migration after verification, restore your pre-migration HA backup. Keep registry backups private.

**Home Assistant Container:** SSH into the Docker host. From the directory mounted as the container’s `/config`, run `sh custom_components/tion_breezer_2026/migrate.sh --container homeassistant` (substitute your container name). The script checks the mount, stops and starts that container, and uses the same backups and conversion. Run it with write access to the config volume, Docker access and jq installed. For interrupted replacement append `--recover`.
