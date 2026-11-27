#!/bin/sh
# Run from the HAOS host or the Terminal & SSH app. The Supervisor stays running.
set -eu
umask 077
component=$(CDPATH='' cd "$(dirname "$0")" && pwd)
config=$(CDPATH='' cd "$component/../.." && pwd)
storage=$config/.storage
base=$storage/tion-migration
files='core.config_entries core.entity_registry core.device_registry'
container=
if [ "${1:-}" = --container ]; then
    container=${2:?Supply the Home Assistant container name}
    shift 2
fi
mode=${1:-migrate}
case "$mode" in migrate|--recover) ;; *) echo "Usage: sh $0 [--container NAME] [--recover]" >&2; exit 2 ;; esac
command -v jq >/dev/null || { echo 'Install jq in this shell first.' >&2; exit 1; }
if [ -n "$container" ]; then
    source=$(docker inspect "$container" | jq -er '.[0].Mounts[] | select(.Destination == "/config") | .Source')
    if [ "$(cd "$source" && pwd -P)" != "$(cd "$config" && pwd -P)" ]; then
        echo "Container /config does not match the directory containing this script." >&2
        exit 1
    fi
    core_stop() { docker stop --time 120 "$container"; }
    core_start() { docker start "$container"; }
else
    command -v ha >/dev/null || { echo 'Use Terminal & SSH on HAOS or pass --container NAME on the Docker host.' >&2; exit 1; }
    core_stop() { ha core stop; }
    core_start() { ha core start; }
fi
jq -e '.domain == "tion_breezer_2026"' "$component/manifest.json" >/dev/null
test -r "$component/migration/registries.jq"
mkdir -p "$base"
lock=$base/lock
if ! mkdir "$lock" 2>/dev/null; then
    echo "Another migration holds $lock. If its shell was killed, confirm it has exited before removing the empty lock directory." >&2
    exit 1
fi
trap 'rmdir "$lock"' EXIT
trap 'exit 1' HUP INT TERM
pending=$base/pending

restore_pending() {
    for file in $files; do
        cp -p "$pending/original/$file" "$pending/restore.tmp"
        mv -f "$pending/restore.tmp" "$storage/$file"
    done
    sync
    mv "$pending" "$(mktemp -d "$base/recovered.XXXXXX")/snapshot"
}

if [ "$mode" = --recover ]; then
    test -d "$pending" || { echo 'No interrupted registry replacement.'; exit 0; }
    core_stop
    restore_pending
    core_start
    exit 0
fi
if [ -e "$pending" ]; then
    echo "Interrupted migration. Run: sh $0 --recover" >&2
    exit 1
fi
stage=$(mktemp -d "$base/backup.XXXXXX")
prepare() {
    mkdir "$stage/original" "$stage/new" || return 1
    for file in $files; do cp -p "$storage/$file" "$stage/original/$file" || return 1; done
    jq -es -f "$component/migration/registries.jq" \
        "$stage/original/core.config_entries" "$stage/original/core.entity_registry" \
        "$stage/original/core.device_registry" > "$stage/converted" || return 1
    index=0
    for file in $files; do
        cp -p "$stage/original/$file" "$stage/new/$file" || return 1
        jq -e ".[$index]" "$stage/converted" > "$stage/new/$file" || return 1
        index=$((index + 1))
    done
    rm "$stage/converted" && sync
}

echo 'Stopping Home Assistant Core to close BLE connections and flush registries.'
core_stop
if ! prepare; then
    rm -rf "$stage"
    echo 'Preparation failed. Original registries are intact. Restarting Core.' >&2
    core_start
    exit 1
fi
count=$(jq '[.data.entries[] | select(.domain == "ha_tion_btle")] | length' "$stage/original/core.config_entries")
mv "$stage" "$pending"
sync
for file in $files; do
    if ! mv -f "$pending/new/$file" "$storage/$file"; then
        echo 'Replacement failed. Restoring all three originals.' >&2
        restore_pending
        core_start
        exit 1
    fi
done
sync
mv "$pending" "$stage"
echo "Migrated $count breezer entries. Original registries: $stage/original"
echo 'Starting Core. Check the migrated entries before uninstalling the old integration.'
core_start
