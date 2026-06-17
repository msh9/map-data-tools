"""AIXM XML parsing for FAA NASR navaid data.

Extracts navaid records from NASR AIXM 5.1 XML files using stdlib iterparse
for streaming, constant-memory processing of large files.

REFACTOR CANDIDATE: The best-effort parsing pattern (parse, collect errors,
continue) is shared with dof2geojson. Consider extracting to a shared module
if a third utility appears.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TextIO

from nasr_aixm2geojson.navaid import NavaidRecord

AIXM_NS = "http://www.aixm.aero/schema/5.1"
GML_NS = "http://www.opengis.net/gml/3.2"
FAA_NS = "http://www.faa.gov/aixm5.1"
NAV_NS = "http://www.faa.gov/aixm5.1/nav"
XLINK_NS = "http://www.w3.org/1999/xlink"

NS = {
    "aixm": AIXM_NS,
    "gml": GML_NS,
    "faa": FAA_NS,
    "nav": NAV_NS,
    "xlink": XLINK_NS,
}

# Qualified element tags for iterparse matching
TAG_FAA_MEMBER = f"{{{FAA_NS}}}Member"
TAG_FAA_SUBSCRIBER_FILE = f"{{{FAA_NS}}}SubscriberFile"

# Navaid element tags (children of faa:Member)
TAG_AIXM_NAVAID = f"{{{AIXM_NS}}}Navaid"
TAG_AIXM_RADIO_COMM_CHANNEL = f"{{{AIXM_NS}}}RadioCommunicationChannel"

NAVAID_TYPES = frozenset(
    {
        "VOR",
        "VOR_DME",
        "VORTAC",
        "NDB",
        "NDB_DME",
        "TACAN",
        "DME",
        "OTHER:VOT",
        "OTHER:FAN_MARKER",
        "OTHER:MARINE_NDB",
    }
)


@dataclass
class ParseSummary:
    """Statistics from parsing an AIXM file."""

    navaid_count: int = 0
    error_count: int = 0
    rcc_count: int = 0


@dataclass
class _RawNavaid:
    """Intermediate holder for navaid data before RCC resolution."""

    navaid_type: str = ""
    designator: str = ""
    name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    elevation_ft: float | None = None
    rcc_ids: list[str] = field(default_factory=list)
    navaid_class: str | None = None
    navaid_status: str | None = None
    state_name: str | None = None
    administrative_area: str | None = None
    associated_city: str | None = None


@dataclass
class _RCCData:
    """RadioCommunicationChannel frequency/channel data."""

    frequency_mhz: float | None = None
    channel: str | None = None


def parse_aixm_file(
    input_path: Path,
    error_stream: TextIO = sys.stderr,
    record_handler: Callable[[NavaidRecord], None] | None = None,
) -> tuple[ParseSummary, str | None]:
    """Parse an AIXM navaid XML file and emit NavaidRecords via callback.

    Returns a ParseSummary and the effective date string (or None).

    Because frequency/channel data lives in separate RadioCommunicationChannel
    elements linked by xlink:href, we collect all navaids and RCCs in a single
    pass, then resolve references and emit records.
    """
    summary = ParseSummary()
    effective_date: str | None = None
    raw_navaids: list[_RawNavaid] = []
    rcc_index: dict[str, _RCCData] = {}

    context = ET.iterparse(str(input_path), events=("start", "end"))

    for event, elem in context:
        if event == "start" and elem.tag == TAG_FAA_SUBSCRIBER_FILE:
            effective_date = elem.get("validFrom")
            continue

        if event != "end" or elem.tag != TAG_FAA_MEMBER:
            continue

        # Process the child element of faa:Member
        child = _first_child_element(elem)
        if child is None:
            elem.clear()
            continue

        try:
            if child.tag == TAG_AIXM_NAVAID:
                raw = _parse_navaid_member(child)
                if raw is not None:
                    raw_navaids.append(raw)
                    summary.navaid_count += 1
            elif child.tag == TAG_AIXM_RADIO_COMM_CHANNEL:
                rcc_id = child.get(f"{{{GML_NS}}}id")
                if rcc_id is not None:
                    rcc_data = _parse_rcc_member(child)
                    rcc_index[rcc_id] = rcc_data
                    summary.rcc_count += 1
        except Exception as exc:
            gml_id = child.get(f"{{{GML_NS}}}id", "unknown")
            print(f"{input_path}: error parsing element {gml_id}: {exc}", file=error_stream)
            summary.error_count += 1

        elem.clear()

    # Resolve RCC references and emit NavaidRecords
    for raw in raw_navaids:
        freq_mhz: float | None = None
        channel: str | None = None

        for rcc_id in raw.rcc_ids:
            rcc = rcc_index.get(rcc_id)
            if rcc is not None:
                if rcc.frequency_mhz is not None and freq_mhz is None:
                    freq_mhz = rcc.frequency_mhz
                if rcc.channel is not None and channel is None:
                    channel = rcc.channel

        record = NavaidRecord(
            navaid_type=raw.navaid_type,
            designator=raw.designator,
            name=raw.name,
            latitude=raw.latitude,
            longitude=raw.longitude,
            elevation_ft=raw.elevation_ft,
            frequency_mhz=freq_mhz,
            channel=channel,
            navaid_class=raw.navaid_class,
            navaid_status=raw.navaid_status,
            state_name=raw.state_name,
            administrative_area=raw.administrative_area,
            associated_city=raw.associated_city,
        )

        if record_handler is not None:
            record_handler(record)

    return summary, effective_date


def _first_child_element(elem: ET.Element) -> ET.Element | None:
    """Return the first child element, or None."""
    for child in elem:
        return child
    return None


def _parse_navaid_member(navaid_elem: ET.Element) -> _RawNavaid | None:
    """Extract navaid data from an aixm:Navaid element."""
    time_slice = navaid_elem.find(f"{{{AIXM_NS}}}timeSlice/{{{AIXM_NS}}}NavaidTimeSlice")
    if time_slice is None:
        return None

    navaid_type = _text(time_slice, f"{{{AIXM_NS}}}type")
    if navaid_type is None or navaid_type not in NAVAID_TYPES:
        return None

    designator = _text(time_slice, f"{{{AIXM_NS}}}designator")
    name = _text(time_slice, f"{{{AIXM_NS}}}name")
    if designator is None or name is None:
        return None

    raw = _RawNavaid(navaid_type=navaid_type, designator=designator, name=name)

    # Parse location
    elevated_point = time_slice.find(f"{{{AIXM_NS}}}location/{{{AIXM_NS}}}ElevatedPoint")
    if elevated_point is not None:
        pos = _text(elevated_point, f"{{{GML_NS}}}pos")
        if pos is not None:
            lon, lat = _parse_gml_pos(pos)
            raw.longitude = lon
            raw.latitude = lat

        elev_text = _text(elevated_point, f"{{{AIXM_NS}}}elevation")
        if elev_text is not None:
            raw.elevation_ft = float(elev_text)

    # Collect RCC xlink references
    for component in time_slice.findall(
        f"{{{AIXM_NS}}}navaidEquipment/{{{AIXM_NS}}}NavaidComponent"
    ):
        href_elem = component.find(f"{{{AIXM_NS}}}theNavaidEquipment")
        if href_elem is not None:
            href = href_elem.get(f"{{{XLINK_NS}}}href", "")
            rcc_id = _extract_rcc_id_from_href(href)
            if rcc_id is not None:
                raw.rcc_ids.append(rcc_id)

    # Parse FAA extension data
    extension = time_slice.find(f"{{{AIXM_NS}}}extension/{{{NAV_NS}}}NavaidExtension")
    if extension is not None:
        raw.navaid_class = _text(extension, f"{{{NAV_NS}}}navaidClass")
        raw.navaid_status = _text(extension, f"{{{NAV_NS}}}navaidStatus")
        raw.state_name = _text(extension, f"{{{NAV_NS}}}stateName")

        city_elem = extension.find(
            f"{{{NAV_NS}}}associatedCity/{{{AIXM_NS}}}City/{{{AIXM_NS}}}name"
        )
        if city_elem is not None and city_elem.text:
            raw.associated_city = city_elem.text.strip()

        contact = extension.find(
            f"{{{NAV_NS}}}contact/{{{AIXM_NS}}}ContactInformation"
            f"/{{{AIXM_NS}}}address/{{{AIXM_NS}}}PostalAddress"
            f"/{{{AIXM_NS}}}administrativeArea"
        )
        if contact is not None and contact.text:
            raw.administrative_area = contact.text.strip()

    return raw


def _parse_rcc_member(rcc_elem: ET.Element) -> _RCCData:
    """Extract frequency/channel from a RadioCommunicationChannel element."""
    data = _RCCData()
    time_slice = rcc_elem.find(
        f"{{{AIXM_NS}}}timeSlice/{{{AIXM_NS}}}RadioCommunicationChannelTimeSlice"
    )
    if time_slice is None:
        return data

    freq_text = _text(time_slice, f"{{{AIXM_NS}}}frequencyTransmission")
    if freq_text is not None:
        try:
            data.frequency_mhz = float(freq_text)
        except ValueError:
            pass

    channel_text = _text(time_slice, f"{{{AIXM_NS}}}channel")
    if channel_text is not None and channel_text:
        data.channel = channel_text

    return data


def _text(parent: ET.Element, tag: str) -> str | None:
    """Get stripped text content of a child element, or None."""
    elem = parent.find(tag)
    if elem is not None and elem.text:
        return elem.text.strip()
    return None


def _parse_gml_pos(pos_text: str) -> tuple[float, float]:
    """Parse a GML pos string into (longitude, latitude).

    FAA NASR AIXM files use CRS83 with lon/lat axis order in gml:pos.
    """
    parts = pos_text.strip().split()
    if len(parts) < 2:
        raise ValueError(f"gml:pos requires at least 2 coordinates, got: {pos_text!r}")
    lon = float(parts[0])
    lat = float(parts[1])
    return lon, lat


def _extract_rcc_id_from_href(href: str) -> str | None:
    """Extract a RadioCommunicationChannel gml:id from an xlink:href.

    Expected format:
    #/faa:SubscriberFile/faa:Member/aixm:RadioCommunicationChannel[@gml:id='RCC_0000001']
    """
    marker = "RadioCommunicationChannel"
    if marker not in href:
        return None

    id_start = href.find("'")
    id_end = href.rfind("'")
    if id_start < 0 or id_end <= id_start:
        return None

    return href[id_start + 1 : id_end]
