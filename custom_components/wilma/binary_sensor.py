"""Binary sensor platform for Wilma integration — self-check problem indicator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BINARY_SENSOR_PROBLEM, DOMAIN
from .coordinator import WilmaCoordinator

_PROBLEM_DESCRIPTION = BinarySensorEntityDescription(
    key=BINARY_SENSOR_PROBLEM,
    name="Problem",
    device_class=BinarySensorDeviceClass.PROBLEM,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Wilma binary sensor platform."""
    coordinator: WilmaCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WilmaProblemBinarySensor(coordinator, entry)])


class WilmaProblemBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that turns ON when any Wilma scrape fails or returns an unexpected HTTP status."""

    entity_description = _PROBLEM_DESCRIPTION

    def __init__(self, coordinator: WilmaCoordinator, entry: ConfigEntry) -> None:
        """Initialize the problem sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_problem"
        self._attr_has_entity_name = True
        self._attr_translation_key = BINARY_SENSOR_PROBLEM
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Wilma",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": "1.0.0",
        }

    @property
    def is_on(self) -> bool:
        """Return True when the last coordinator update failed or partial fetch errors occurred."""
        if not self.coordinator.last_update_success:
            return True
        return bool(self.coordinator.last_fetch_errors)

    @property
    def extra_state_attributes(self) -> dict:
        """Return fetch error details when in problem state."""
        return {"errors": list(self.coordinator.last_fetch_errors)}
