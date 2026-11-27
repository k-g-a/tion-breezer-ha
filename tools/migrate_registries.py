"""Prepare a migrated copy of Home Assistant's Tion registries, offline."""
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

OLD = "ha_tion_btle"
NEW = "tion_breezer_2026"
FILES = ("core.config_entries", "core.entity_registry", "core.device_registry")


def migrate(entries, entities, devices):
    selected = {e["entry_id"]: e for e in entries["entries"] if e["domain"] == OLD}
    if not selected:
        raise ValueError("No ha_tion_btle entries found")
    if any(e["domain"] == NEW for e in entries["entries"]):
        raise ValueError("Destination already has config entries")
    macs = set()
    for e in selected.values():
        mac = e["data"]["mac"]
        if not mac or mac in macs or e["unique_id"] not in (None, mac):
            raise ValueError("Unexpected or duplicate breezer identity")
        macs.add(mac)
        e["domain"] = NEW

    entity_count = 0
    for e in entities["entities"] + entities.get("deleted_entities", []):
        if e["platform"] == NEW:
            raise ValueError("Destination already has registered entities")
        if e["platform"] == OLD and e.get("config_entry_id") in selected:
            e["platform"] = NEW
            entity_count += 1
        elif e["platform"] == OLD and e in entities["entities"]:
            raise ValueError("Found an active legacy entity without a matching entry")

    device_count = 0
    for d in devices["devices"] + devices.get("deleted_devices", []):
        ids = d["identifiers"]
        if any(namespace == NEW for namespace, _ in ids):
            raise ValueError("Destination already has registered devices")
        for identity in ids:
            if identity[0] == OLD and identity[1] in macs:
                identity[0] = NEW
                device_count += 1
            elif identity[0] == OLD and d in devices["devices"]:
                raise ValueError("Found an active legacy device with an unknown identity")
        if d.get("domain") == OLD and any(ns == NEW for ns, _ in ids):
            d["domain"] = NEW
    return len(selected), entity_count, device_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="directory with copies of all three files")
    parser.add_argument("--output", type=Path, help="new directory for the migrated copies")
    args = parser.parse_args()
    documents = []
    for name in FILES:
        doc = json.loads((args.source / name).read_bytes())
        if doc.get("key") != name:
            parser.error(f"Unexpected storage key in {name}")
        documents.append(doc)
    counts = migrate(*(doc["data"] for doc in documents))
    print("Config entries: %d, entity records: %d, device identifiers: %d" % counts)
    if args.output:
        if args.output.exists():
            parser.error("Choose a new output directory")
        with TemporaryDirectory(dir=args.output.parent) as tmp:
            stage = Path(tmp) / "registries"
            stage.mkdir(mode=0o700)
            for name, doc in zip(FILES, documents, strict=True):
                with (stage / name).open("x", encoding="utf-8") as f:
                    os.fchmod(f.fileno(), 0o600)
                    json.dump(doc, f, ensure_ascii=False, indent=2)
                    f.write("\n")
            stage.rename(args.output)


if __name__ == "__main__":
    main()
