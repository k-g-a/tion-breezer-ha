"""Prepare a migrated copy of Home Assistant's Tion registries, offline."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

OLD = "ha_tion_btle"
NEW = "tion_breezer_2026"
FILES = ("core.config_entries", "core.entity_registry", "core.device_registry")


def migrate(entries, entities, devices):
    program = (Path(__file__).resolve().parents[1] / "custom_components" /
               NEW / "migration" / "registries.jq")
    registries = [entries, entities, devices]
    documents = [{"key": key, "data": data} for key, data in zip(FILES, registries, strict=True)]
    result = subprocess.run(["jq", "-e", "-f", str(program)], input=json.dumps(documents),
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip())
    converted = json.loads(result.stdout)
    for data, doc in zip(registries, converted, strict=True):
        data.update(doc["data"])
    return (sum(e["domain"] == NEW for e in entries["entries"]),
            sum(e["platform"] == NEW for e in entities["entities"] + entities.get("deleted_entities", [])),
            sum(ns == NEW for d in devices["devices"] + devices.get("deleted_devices", [])
                for ns, _ in d["identifiers"]))


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
