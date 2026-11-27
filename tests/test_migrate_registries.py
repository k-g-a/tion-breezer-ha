"""Exercise the offline domain migration without a Home Assistant installation."""
import unittest

from tools.migrate_registries import migrate, NEW, OLD


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.entries = {"entries": [
            {"entry_id": str(i), "domain": OLD, "unique_id": f"mac{i}",
             "data": {"mac": f"mac{i}"}, "options": {"keep_alive": 60}}
            for i in range(4)
        ]}
        self.entities = {"entities": [
            {"platform": OLD, "config_entry_id": str(i), "entity_id": f"fan.room_{i}"}
            for i in range(4)
        ]}
        self.devices = {"devices": [
            {"id": f"device{i}", "identifiers": [[OLD, f"mac{i}"], ["other", str(i)]]}
            for i in range(4)
        ]}

    def test_four_entries_and_shared_device(self):
        unrelated = {"domain": "other", "entry_id": "foreign"}
        self.entries["entries"].append(unrelated)
        self.entities["deleted_entities"] = [{"platform": OLD, "config_entry_id": "1"}]
        self.assertEqual(migrate(self.entries, self.entities, self.devices), (4, 5, 4))
        self.assertEqual(self.entries["entries"][-1], unrelated)
        for i in range(4):
            self.assertEqual(self.entries["entries"][i], {
                "entry_id": str(i), "domain": NEW, "unique_id": f"mac{i}",
                "data": {"mac": f"mac{i}"}, "options": {"keep_alive": 60}})
            self.assertEqual(self.entities["entities"][i], {
                "platform": NEW, "config_entry_id": str(i), "entity_id": f"fan.room_{i}"})
            self.assertEqual(self.devices["devices"][i], {
                "id": f"device{i}", "identifiers": [[NEW, f"mac{i}"], ["other", str(i)]]})
        self.assertEqual(self.entities["deleted_entities"][0]["platform"], NEW)

    def test_conflicting_destination(self):
        self.devices["devices"].append({"identifiers": [[NEW, "mac1"]]})
        with self.assertRaisesRegex(ValueError, "Destination"):
            migrate(self.entries, self.entities, self.devices)


if __name__ == "__main__":
    unittest.main()
