"""Run the packaged SSH command against a disposable HA config volume."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.migrate_registries import FILES, NEW, OLD


class CommandTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        component = self.root / "custom_components" / NEW
        src = Path(__file__).resolve().parents[1] / "custom_components" / NEW
        shutil.copytree(src, component)
        self.script = component / "migrate.sh"
        self.storage = self.root / ".storage"
        self.storage.mkdir()
        self.data = [
            {"entries": [{"entry_id": "a", "domain": OLD, "data": {"mac": "MAC"},
                          "unique_id": None, "disabled_by": "user"}]},
            {"entities": [{"config_entry_id": "a", "entity_id": "fan.office", "platform": OLD}]},
            {"devices": [{"id": "office", "identifiers": [[OLD, "MAC"]]}]},
        ]
        self.original = {}
        for name, data in zip(FILES, self.data, strict=True):
            content = json.dumps({"key": name, "data": data})
            (self.storage / name).write_text(content)
            self.original[name] = content
        self.command_log = self.root / "calls"
        ha = self.root / "ha"
        ha.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\n')
        ha.chmod(0o700)
        self.env = dict(os.environ, PATH=f"{self.root}:{os.environ['PATH']}", CALLS=str(self.command_log))

    def invoke(self, *args):
        return subprocess.run(["sh", str(self.script), *args], env=self.env,
                              capture_output=True, text=True)

    def test_complete(self):
        run = self.invoke()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Migrated 1 breezer", run.stdout)
        self.assertEqual(self.command_log.read_text().splitlines(), ["core stop", "core start"])
        self.assertEqual(json.loads((self.storage / FILES[0]).read_text())["data"]["entries"][0],
                         dict(self.data[0]["entries"][0], domain=NEW))
        backup, = (self.storage / "tion-migration").glob("backup.*/original")
        for name in FILES:
            self.assertEqual((backup / name).read_text(), self.original[name])

    def test_conflict_leaves_originals(self):
        dst = self.storage / FILES[1]
        dst.write_text(dst.read_text().replace(OLD, NEW))
        before = [ (self.storage / name).read_bytes() for name in FILES ]
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(before, [(self.storage / name).read_bytes() for name in FILES])
        self.assertEqual(self.command_log.read_text().splitlines(), ["core stop", "core start"])

    def test_interrupted_replacement(self):
        original = self.storage / "tion-migration/pending/original"
        original.mkdir(parents=True)
        for name in FILES:
            shutil.copyfile(self.storage / name, original / name)
        (self.storage / FILES[0]).write_text("partially migrated")
        self.assertNotEqual(self.invoke().returncode, 0)
        run = self.invoke("--recover")
        self.assertEqual(run.returncode, 0, run.stderr)
        for name in FILES:
            self.assertEqual((self.storage / name).read_text(), self.original[name])

    def test_container_mount_and_lifecycle(self):
        docker = self.root / "docker"
        docker.write_text('#!/bin/sh\nif [ "$1" = inspect ]; then echo "$INSPECT"; '
                          'else echo "$*" >> "$CALLS"; fi\n')
        docker.chmod(0o700)
        for source, success in ((self.storage, False), (self.root, True)):
            self.env["INSPECT"] = json.dumps([{"Mounts": [{"Destination": "/config", "Source": str(source)}]}])
            run = self.invoke("--container", "ha")
            self.assertEqual(run.returncode == 0, success, run.stderr)
            if not success:
                self.assertFalse(self.command_log.exists())
        self.assertEqual(self.command_log.read_text().splitlines(), ["stop --time 120 ha", "start ha"])
