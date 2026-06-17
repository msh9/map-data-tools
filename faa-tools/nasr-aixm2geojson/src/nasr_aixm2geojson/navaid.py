"""Navaid data model and normalization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavaidRecord:
    """Parsed navaid from AIXM data."""

    navaid_type: str
    designator: str
    name: str
    latitude: float
    longitude: float
    elevation_ft: float | None
    frequency_mhz: float | None
    channel: str | None
    navaid_class: str | None
    navaid_status: str | None
    state_name: str | None
    administrative_area: str | None
    associated_city: str | None

    def to_normalized_dict(self) -> dict[str, object]:
        """Convert to normalized dictionary for GeoJSON feature creation."""
        result: dict[str, object] = {
            "navaid_id": f"{self.designator}-{self.navaid_type}",
            "navaid_type": self.navaid_type,
            "designator": self.designator,
            "name": self.name,
            "location": {
                "latitude": self.latitude,
                "longitude": self.longitude,
            },
        }

        if self.elevation_ft is not None:
            result["elevation"] = {
                "feet": self.elevation_ft,
                "meters": round(self.elevation_ft * 0.3048, 3),
            }

        frequency: dict[str, object] = {}
        if self.frequency_mhz is not None:
            frequency["mhz"] = self.frequency_mhz
        if self.channel is not None:
            frequency["channel"] = self.channel
        if frequency:
            result["frequency"] = frequency

        if self.navaid_class is not None:
            result["navaid_class"] = self.navaid_class
        if self.navaid_status is not None:
            result["navaid_status"] = self.navaid_status
        if self.state_name is not None:
            result["state_name"] = self.state_name
        if self.administrative_area is not None:
            result["administrative_area"] = self.administrative_area
        if self.associated_city is not None:
            result["associated_city"] = self.associated_city

        return result
