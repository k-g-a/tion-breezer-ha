"""Maintenance actions for Tion breezers."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TionInstance
from .const import DOMAIN


BUTTON_TYPES: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="reset_filter",
        name="Reset filter resource",
        icon="mdi:air-filter",
        entity_category=EntityCategory.CONFIG,
    ),
    ButtonEntityDescription(
        key="reset_errors",
        name="Reset errors",
        icon="mdi:alert-remove",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up 4S maintenance buttons."""
    instance: TionInstance = hass.data[DOMAIN][config_entry.unique_id]
    if instance.model != "S4":
        return

    async_add_entities(TionButton(description, instance) for description in BUTTON_TYPES)


class TionButton(CoordinatorEntity, ButtonEntity):
    """Execute a one-shot Tion maintenance action."""

    coordinator: TionInstance

    def __init__(self, description: ButtonEntityDescription, instance: TionInstance) -> None:
        super().__init__(instance)
        self.entity_description = description
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"

    async def async_press(self) -> None:
        """Execute the requested action."""
        await self.coordinator.set(**{self.entity_description.key: True})
