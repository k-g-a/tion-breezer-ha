# Bluetooth pairing and troubleshooting

[Русский](bluetooth.ru.md)

The pairing recovery and Linux diagnostics below are adapted from **Igor Tkachenko (@IATkachenko)**, author of the original [HA-tion wiki](https://github.com/TionAPI/HA-tion/wiki) and its [Bluetooth guide](https://github.com/TionAPI/HA-tion/wiki/Bluetooth). The hardware observation below is from this fork's maintainer.

**Four Tion 4S breezers are working stably in the maintainer's installation in 2026. Only manual pairing with `bluetoothctl` worked for those units.** Existing working bonds survive an integration-domain migration.

## Setup fails or readings stop after pairing

Disconnect the phone app, remote, other integrations and BLE monitors. If the first pairing attempt gives an error, put the breezer back into pairing mode, clear **Need pair** in the integration and retry. If readings stop shortly after setup, inspect the bond on the Linux host that owns the local adapter. On HAOS use the [host console or SSH on port 22222](https://contributors.home-assistant.io/os/operating-system/debugging/). The Terminal & SSH app runs in a container. These paths apply to a local BlueZ adapter.

The file is `/var/lib/bluetooth/<adapter-MAC>/<breezer-MAC>/info`. The upstream example for a 3S has a `[General]` section with the name, static address type, LE support, trust/block flags and service UUIDs. That section alone does not establish that bonding succeeded. Igor's example also has `[IdentityResolvingKey]` and `[LongTermKey]`. Inspect section names only, for example with `grep '^\[' info` in the device directory. Keep key values private.

### Rebuild a missing bond

1. Remove the failed breezer entry from HA. Reserve this procedure for a broken bond. For a working installation changing domains, use the [migration guide](development-and-migration.md).
2. On the BlueZ host, open `bluetoothctl` as root (use `sudo bluetoothctl` on ordinary Linux). Run `list`, then `select ADAPTER_MAC` and `remove BREEZER_MAC`. Substitute the actual addresses. This targets only the stale bond on the selected adapter. Igor's original procedure removes the corresponding device directory under `/var/lib/bluetooth/` and restarts Bluetooth with `systemctl restart bluetooth`. Restarting Bluetooth interrupts all devices on the host.
3. Activate pairing mode on the breezer. In `bluetoothctl` on the correct adapter, run:

   ```text
   power on
   agent on
   scan on
   pair BREEZER_MAC
   scan off
   info BREEZER_MAC
   ```

4. Confirm pairing succeeded and check the key sections again. Add the breezer in HA with **Need pair** cleared. Verify several successive readings.

## Linux and adapter diagnostics

- Test visibility and pairing with `bluetoothctl` on the host. If adding a device still fails, enable integration debug logging and reproduce the failure.
- On a Raspberry Pi, try an external adapter on a USB extension cable to move it away from interference.
- For a non-root Linux service, Igor's 2021 guide checks Bluetooth group membership, the old `bluetooth_le_tracker` executable capabilities (`setcap`), `bluetoothd --compat`, `/var/run/sdp` permissions and the service user's system D-Bus policy in `/etc/dbus-1/system.d/bluetooth.conf`. Its example covers `org.bluez`, Agent1, GattCharacteristic1, GattDescriptor1 and the D-Bus ObjectManager and Properties interfaces. These checks describe older installations.
- The same guide describes host networking, USB device passthrough, `--privileged`, and mounting the USB bus and D-Bus socket for historical containers. For a current HA Container deployment, follow the [HA Bluetooth requirements](https://www.home-assistant.io/integrations/bluetooth/): host BlueZ, the host D-Bus socket and the documented NET_ADMIN/NET_RAW capabilities. HAOS manages its own Bluetooth permissions.
- On a dedicated LE-only host adapter, the upstream guide suggests experimenting with `ControllerMode = le` and `FastConnectable = true` in `/etc/bluetooth/main.conf`. Save the original settings first. Controller mode affects other devices and disables classic Bluetooth when set to LE.
- Upstream [issue #30](https://github.com/TionAPI/HA-tion/issues/30) describes an Ubuntu adapter recovering after `sudo modprobe -r btusb` followed by `sudo modprobe btusb`. Reloading the driver disconnects every adapter using it. See the original Bluetooth guide for these historical workarounds.
