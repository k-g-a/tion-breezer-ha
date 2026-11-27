"""Consts for Tion component"""
from homeassistant.components.climate import PLATFORM_SCHEMA
from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE,
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_SLEEP,
    PRESET_NONE,
 )
from homeassistant.const import (ATTR_TEMPERATURE, CONF_NAME, EVENT_HOMEASSISTANT_START, PRECISION_WHOLE, Platform, )
from voluptuous import All, Coerce, In, Range
DOMAIN = 'tion_breezer_2026'
DEFAULT_NAME = "Tion Breezer 2026"
DEFAULT_BOOST_DURATION_MINUTES = 5

CONF_TARGET_TEMP = "target_temp"
CONF_KEEP_ALIVE = "keep_alive"
CONF_INITIAL_HVAC_MODE = "initial_hvac_mode"
CONF_AWAY_TEMP = "away_temp"
CONF_BOOST_DURATION = "boost_duration"
CONF_MAC = "mac"
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.FAN,
]
SUPPORTED_DEVICES = ['S3', 'S4', 'Lite']

TION_SCHEMA = {
    'model': {'type': All(str, In(SUPPORTED_DEVICES)), 'required': True},
    'name': {'type': str, 'default': DEFAULT_NAME, 'required': True},
    CONF_MAC: {'type': str, 'required': True},
    CONF_KEEP_ALIVE: {'type': int, 'default': 60, 'required': False},
    CONF_AWAY_TEMP: {'type': int, 'default': 15, 'required': False},
    CONF_BOOST_DURATION: {
        'type': All(Coerce(int), Range(min=1, max=1092)),
        'default': DEFAULT_BOOST_DURATION_MINUTES,
        'required': False,
    },
    'pair': {'type': bool, 'default': True, 'required': False},
}
