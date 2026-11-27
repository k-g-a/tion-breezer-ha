"""Run inside either supported Home Assistant test image."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homeassistant.components.climate import ClimateEntity
from custom_components.tion_breezer_2026.climate import TionClimateEntity

entity = object.__new__(TionClimateEntity)
entity.coordinator = SimpleNamespace(data={}, supports_native_boost=False, last_update_success=True)
prefix = "native_" if hasattr(ClimateEntity, "native_temperature_unit") else ""
for target, current in ((None, None), (21, -4), (0, 0)):
    entity.coordinator.data = {"heater_temp": target, "out_temp": current}
    entity._get_current_state()
    assert getattr(entity, prefix + "temperature_unit") == "°C"
    assert getattr(entity, prefix + "target_temperature") == target
    assert getattr(entity, prefix + "current_temperature") == current
