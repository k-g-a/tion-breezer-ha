"""Binary state sensors for Tion breezers."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TionInstance
from .const import DOMAIN


BINARY_SENSOR_TYPES: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="device_problem",
        name="Device problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="filter_change_required",
        name="Filter replacement required",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="heater_active",
        name="Heater active",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    BinarySensorEntityDescription(
        key="timer_active",
        name="Built-in timer active",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="magicair_connected",
        name="MagicAir connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="magicair_auto",
        name="MagicAir automatic control",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up 4S binary sensors."""
    instance: TionInstance = hass.data[DOMAIN][config_entry.unique_id]
    if instance.model != "S4":
        return

    async_add_entities(TionBinarySensor(description, instance) for description in BINARY_SENSOR_TYPES)


class TionBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Represent a boolean Tion state."""

    coordinator: TionInstance

    def __init__(self, description: BinarySensorEntityDescription, instance: TionInstance) -> None:
        super().__init__(instance)
        self.entity_description = description
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(self.entity_description.key))

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.key != "device_problem":
            return None
        return {
            "active_error_codes": self.coordinator.data.get("active_error_codes", []),
            "raw_error_code": self.coordinator.data.get("request_error_code", 0),
        }

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
