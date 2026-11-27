"""Configuration switches for Tion breezers."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TionInstance
from .const import DOMAIN


SOUND_SWITCH = SwitchEntityDescription(
    key="sound",
    name="Sound indication",
    icon="mdi:volume-high",
    entity_category=EntityCategory.CONFIG,
)

LIGHT_SWITCH = SwitchEntityDescription(
    key="light",
    name="Light indication",
    icon="mdi:led-on",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Tion configuration switches."""
    instance: TionInstance = hass.data[DOMAIN][config_entry.unique_id]
    descriptions = [SOUND_SWITCH]
    if instance.model in ("S4", "Lite"):
        descriptions.append(LIGHT_SWITCH)

    async_add_entities(TionSwitch(description, instance) for description in descriptions)


class TionSwitch(CoordinatorEntity, SwitchEntity):
    """Control a persisted Tion preference."""

    coordinator: TionInstance

    def __init__(self, description: SwitchEntityDescription, instance: TionInstance) -> None:
        super().__init__(instance)
        self.entity_description = description
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"

    @property
    def is_on(self) -> bool:
        """Return whether the preference is enabled."""
        return self.coordinator._decode_state(self.coordinator.data.get(self.entity_description.key, "off"))

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the preference."""
        await self.coordinator.set(**{self.entity_description.key: "on"})

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the preference."""
        await self.coordinator.set(**{self.entity_description.key: "off"})

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
