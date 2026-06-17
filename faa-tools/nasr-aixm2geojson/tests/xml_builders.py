"""XML builder helpers for NASR AIXM navaid tests."""

from __future__ import annotations

import re

_SUBSCRIBER_FILE_OPEN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<faa:SubscriberFile gml:id="Subscriber-0000000"'
    ' validFrom="{valid_from}"'
    ' AIXMVersion="AIXM5.1" SubscriberFileType="NAV"'
    ' xmlns:faa="http://www.faa.gov/aixm5.1"'
    ' xmlns:nav="http://www.faa.gov/aixm5.1/nav"'
    ' xmlns:gml="http://www.opengis.net/gml/3.2"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xmlns:aixm="http://www.aixm.aero/schema/5.1"'
    ' xmlns:xlink="http://www.w3.org/1999/xlink">'
)

_SUBSCRIBER_FILE_CLOSE = "</faa:SubscriberFile>"


def _build_navaid_component(navaid_id: str, index: int, rcc_id: str) -> str:
    return (
        f"<aixm:navaidEquipment>"
        f'<aixm:NavaidComponent gml:id="{navaid_id}_NAV_COMPONENT_{index}">'
        f"<aixm:theNavaidEquipment xlink:href="
        f'"#/faa:SubscriberFile/faa:Member/'
        f"aixm:RadioCommunicationChannel%5B@gml:id='{rcc_id}'%5D\"/>"
        f"</aixm:NavaidComponent>"
        f"</aixm:navaidEquipment>"
    )


def _build_navaid_member(
    *,
    navaid_id: str,
    navaid_type: str,
    designator: str,
    name: str,
    lon: str,
    lat: str,
    elevation_ft: str,
    rcc_refs: list[str],
    navaid_class: str,
    navaid_status: str,
    state_name: str,
    admin_area: str,
    city_name: str,
    valid_from: str,
) -> str:
    components = "".join(
        _build_navaid_component(navaid_id, i, rcc_id) for i, rcc_id in enumerate(rcc_refs, 1)
    )

    return (
        f"<faa:Member>"
        f'<aixm:Navaid gml:id="{navaid_id}">'
        f"<aixm:timeSlice>"
        f'<aixm:NavaidTimeSlice gml:id="{navaid_id}_TS">'
        f"<gml:validTime>"
        f'<gml:TimePeriod gml:id="{navaid_id}_TIME">'
        f"<gml:beginPosition>{valid_from}</gml:beginPosition>"
        f'<gml:endPosition indeterminatePosition="unknown"/>'
        f"</gml:TimePeriod>"
        f"</gml:validTime>"
        f"<aixm:interpretation>BASELINE</aixm:interpretation>"
        f"<aixm:type>{navaid_type}</aixm:type>"
        f"<aixm:designator>{designator}</aixm:designator>"
        f"<aixm:name>{name}</aixm:name>"
        f"{components}"
        f"<aixm:location>"
        f'<aixm:ElevatedPoint gml:id="{navaid_id}_POINT"'
        f' srsName="urn:ogc:def:crs:OGC:1.3:CRS83">'
        f"<gml:pos>{lon} {lat}</gml:pos>"
        f'<aixm:elevation uom="FT">{elevation_ft}</aixm:elevation>'
        f"</aixm:ElevatedPoint>"
        f"</aixm:location>"
        f"<aixm:extension>"
        f'<nav:NavaidExtension gml:id="{navaid_id}_EXT">'
        f"<nav:navaidClass>{navaid_class}</nav:navaidClass>"
        f"<nav:navaidStatus>{navaid_status}</nav:navaidStatus>"
        f"<nav:stateName>{state_name}</nav:stateName>"
        f"<nav:associatedCity>"
        f'<aixm:City gml:id="{navaid_id}_CITY">'
        f"<aixm:name>{city_name}</aixm:name>"
        f"</aixm:City>"
        f"</nav:associatedCity>"
        f"<nav:contact>"
        f'<aixm:ContactInformation gml:id="{navaid_id}_CONTACT">'
        f"<aixm:address>"
        f'<aixm:PostalAddress gml:id="{navaid_id}_ADDR">'
        f"<aixm:administrativeArea>{admin_area}</aixm:administrativeArea>"
        f"</aixm:PostalAddress>"
        f"</aixm:address>"
        f"</aixm:ContactInformation>"
        f"</nav:contact>"
        f"</nav:NavaidExtension>"
        f"</aixm:extension>"
        f"</aixm:NavaidTimeSlice>"
        f"</aixm:timeSlice>"
        f"</aixm:Navaid>"
        f"</faa:Member>"
    )


def _build_rcc_member(
    *,
    rcc_id: str,
    frequency_mhz: str,
    channel: str,
    valid_from: str,
) -> str:
    channel_xml = f"<aixm:channel>{channel}</aixm:channel>" if channel else "<aixm:channel/>"
    return (
        f"<faa:Member>"
        f'<aixm:RadioCommunicationChannel gml:id="{rcc_id}">'
        f"<aixm:timeSlice>"
        f'<aixm:RadioCommunicationChannelTimeSlice gml:id="RCC_TS_{rcc_id}">'
        f"<gml:validTime>"
        f'<gml:TimePeriod gml:id="RCC_TIME_{rcc_id}">'
        f"<gml:beginPosition>{valid_from}</gml:beginPosition>"
        f'<gml:endPosition indeterminatePosition="unknown"/>'
        f"</gml:TimePeriod>"
        f"</gml:validTime>"
        f"<aixm:interpretation>BASELINE</aixm:interpretation>"
        f'<aixm:frequencyTransmission uom="MHZ">{frequency_mhz}</aixm:frequencyTransmission>'
        f"{channel_xml}"
        f"</aixm:RadioCommunicationChannelTimeSlice>"
        f"</aixm:timeSlice>"
        f"</aixm:RadioCommunicationChannel>"
        f"</faa:Member>"
    )


def build_aixm_navaid_xml(
    *,
    navaid_id: str = "NAVAID_0000001",
    navaid_type: str = "VOR_DME",
    designator: str = "SLC",
    name: str = "SALT LAKE CITY",
    lon: str = "-111.979722",
    lat: str = "40.850556",
    elevation_ft: str = "4220.0",
    rcc_refs: list[str] | None = None,
    navaid_class: str = "H-VORW/DME",
    navaid_status: str = "OPERATIONAL IFR",
    state_name: str = "UTAH",
    admin_area: str = "UT",
    city_name: str = "SALT LAKE CITY",
    valid_from: str = "2025-11-27T00:00:00.000-05:00",
) -> str:
    """Build a minimal AIXM XML with a single navaid (no RCC)."""
    if rcc_refs is None:
        rcc_refs = ["RCC_0000001"]

    member = _build_navaid_member(
        navaid_id=navaid_id,
        navaid_type=navaid_type,
        designator=designator,
        name=name,
        lon=lon,
        lat=lat,
        elevation_ft=elevation_ft,
        rcc_refs=rcc_refs,
        navaid_class=navaid_class,
        navaid_status=navaid_status,
        state_name=state_name,
        admin_area=admin_area,
        city_name=city_name,
        valid_from=valid_from,
    )
    return _SUBSCRIBER_FILE_OPEN.format(valid_from=valid_from) + member + _SUBSCRIBER_FILE_CLOSE


def build_full_aixm_xml(
    navaid_kwargs: dict | None = None,
    rcc_kwargs: dict | None = None,
) -> str:
    """Build a complete AIXM XML file with a navaid and its RCC."""
    navaid_kwargs = navaid_kwargs or {}
    rcc_kwargs = rcc_kwargs or {}

    valid_from = navaid_kwargs.get("valid_from", "2025-11-27T00:00:00.000-05:00")

    if rcc_kwargs.get("rcc_refs") is None and "rcc_refs" not in navaid_kwargs:
        rcc_id = rcc_kwargs.get("rcc_id", "RCC_0000001")
        navaid_kwargs.setdefault("rcc_refs", [rcc_id])

    member_navaid = _build_navaid_member(
        navaid_id=navaid_kwargs.get("navaid_id", "NAVAID_0000001"),
        navaid_type=navaid_kwargs.get("navaid_type", "VOR_DME"),
        designator=navaid_kwargs.get("designator", "SLC"),
        name=navaid_kwargs.get("name", "SALT LAKE CITY"),
        lon=navaid_kwargs.get("lon", "-111.979722"),
        lat=navaid_kwargs.get("lat", "40.850556"),
        elevation_ft=navaid_kwargs.get("elevation_ft", "4220.0"),
        rcc_refs=navaid_kwargs.get("rcc_refs", ["RCC_0000001"]),
        navaid_class=navaid_kwargs.get("navaid_class", "H-VORW/DME"),
        navaid_status=navaid_kwargs.get("navaid_status", "OPERATIONAL IFR"),
        state_name=navaid_kwargs.get("state_name", "UTAH"),
        admin_area=navaid_kwargs.get("admin_area", "UT"),
        city_name=navaid_kwargs.get("city_name", "SALT LAKE CITY"),
        valid_from=valid_from,
    )

    member_rcc = _build_rcc_member(
        rcc_id=rcc_kwargs.get("rcc_id", "RCC_0000001"),
        frequency_mhz=rcc_kwargs.get("frequency_mhz", "116.80"),
        channel=rcc_kwargs.get("channel", "115X"),
        valid_from=valid_from,
    )

    return (
        _SUBSCRIBER_FILE_OPEN.format(valid_from=valid_from)
        + member_navaid
        + member_rcc
        + _SUBSCRIBER_FILE_CLOSE
    )


def extract_members(xml: str) -> list[str]:
    """Extract all faa:Member blocks from an AIXM XML string."""
    return re.findall(r"<faa:Member>.*?</faa:Member>", xml, re.DOTALL)
