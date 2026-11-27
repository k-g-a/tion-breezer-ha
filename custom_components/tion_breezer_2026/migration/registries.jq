def require($ok; $message): if $ok then . else error($message) end;
def records($key; $field):
  require(.key == $key and (.data[$field] | type) == "array"; "Unexpected registry format: " + $key);

.[0] |= records("core.config_entries"; "entries") |
.[1] |= records("core.entity_registry"; "entities") |
.[2] |= records("core.device_registry"; "devices") |
"ha_tion_btle" as $old | "tion_breezer_2026" as $new |
[.[0].data.entries[] | select(.domain == $old)] as $entries |
require(($entries | length) > 0; "No legacy ha_tion_btle entries found") |
require(all(.[0].data.entries[]; .domain != $new); "Destination entries already exist") |
require(all($entries[]; (.entry_id | type) == "string" and
  (.data.mac | type) == "string" and (.data.mac | length) > 0 and
  (.unique_id == null or .unique_id == .data.mac)); "Unexpected legacy identity") |
[$entries[].data.mac] as $macs | [$entries[].entry_id] as $ids |
require(($macs | map(ascii_upcase) | unique | length) == ($entries | length); "Duplicate breezer addresses") |
def selected_entry: .config_entry_id as $id | $ids | index($id) != null;
def selected_identifier: .[1] as $mac | .[0] == $old and ($macs | index($mac) != null);
require(all((.[1].data.entities[], .[1].data.deleted_entities[]?); .platform != $new); "Destination entities already exist") |
require(all(.[1].data.entities[]; .platform != $old or selected_entry); "Legacy entity has no matching entry") |
require(all((.[2].data.devices[], .[2].data.deleted_devices[]?) | .identifiers[]; .[0] != $new); "Destination devices already exist") |
require(all(.[2].data.devices[] | .identifiers[]; .[0] != $old or selected_identifier); "Legacy device has an unknown address") |
(.[0].data.entries[] | select(.domain == $old) | .domain) = $new |
((.[1].data.entities[], .[1].data.deleted_entities[]?) | select(.platform == $old and selected_entry) | .platform) = $new |
((.[2].data.devices[], .[2].data.deleted_devices[]?) | select(.domain == $old and any(.identifiers[]; selected_identifier)) | .domain) = $new |
((.[2].data.devices[], .[2].data.deleted_devices[]?) | .identifiers[] | select(selected_identifier) | .[0]) = $new
