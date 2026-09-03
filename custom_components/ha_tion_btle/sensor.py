"""
Sensors for Tion breezers
"""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntityDescription, SensorDeviceClass, SensorStateClass, SensorEntity
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TionInstance
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="in_temp",
        name="input temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        icon="mdi:import",
    ),
    SensorEntityDescription(
        key="out_temp",
        name="output temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
        icon="mdi:export",
    ),
    SensorEntityDescription(
        key="filter_remain",
        name="filters remain",
        entity_registry_enabled_default=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),

    SensorEntityDescription(
        key="fan_speed",
        name="current fan speed",
        entity_registry_enabled_default=True,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
    ),
    SensorEntityDescription(
        key="rssi",
        name="rssi",
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:access-point",
    ),
)

S4_SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="pcb_control_temp",
        name="Controller board temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="pcb_power_temp",
        name="Power board temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="heater_output",
        name="Heater output",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radiator",
    ),
    SensorEntityDescription(
        key="airflow_total",
        name="Total airflow",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:weather-windy",
    ),
    SensorEntityDescription(
        key="work_time",
        name="Operating time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="fan_time",
        name="Fan time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="airflow_counter",
        name="Raw airflow counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="heater_power_rating",
        name="Heater power rating",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="max_fan_speed",
        name="Maximum fan speed",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:fan-plus",
    ),
    SensorEntityDescription(
        key="comm_source",
        name="Communication source",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:remote",
    ),
)


async def async_setup_platform(_hass: HomeAssistant, _config, _async_add_entities, _discovery_info=None):
    _LOGGER.critical("Sensors configuration via configuration.yaml is not supported!")
    return False


async def async_setup_entry(hass: HomeAssistant, config: ConfigEntry, async_add_entities):
    """Set up the sensor entry"""
    tion_instance = hass.data[DOMAIN][config.unique_id]
    descriptions = list(SENSOR_TYPES)
    if tion_instance.model == "S4":
        descriptions.extend(S4_SENSOR_TYPES)
    entities: list[TionSensor] = [
        TionSensor(description, tion_instance) for description in descriptions]
    async_add_entities(entities)

    return True


class TionSensor(SensorEntity, CoordinatorEntity):
    """Representation of a sensor."""

    def __init__(self, description: SensorEntityDescription, instance: TionInstance):
        """Initialize the sensor."""

        CoordinatorEntity.__init__(
            self=self,
            coordinator=instance,
        )
        self.entity_description = description
        self._attr_name = f"{instance.name} {description.name}"
        self._attr_device_info = instance.device_info
        self._attr_unique_id = f"{instance.unique_id}-{description.key}"

        _LOGGER.debug(f"Init of sensor {self.name} ({instance.unique_id})")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        value = self.coordinator.data.get(self.entity_description.key)

        if self.entity_description.key == "fan_speed":
            if not self.coordinator.data.get("is_on"):
                # return zero fan speed if breezer turned off
                value = 0

        return value

    def _handle_coordinator_update(self) -> None:
        self._attr_assumed_state = False if self.coordinator.last_update_success else True
        self.async_write_ha_state()
