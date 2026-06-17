## ADR-005 Zooming

The following is more a specification decision and less architecture, but it the nonetheless impacts applications across the project and thus deserves an ADR.

### Decision:

- Zooming of raster data is correlated to available resolutions (expressed as coordinate reference system units / pixel). For this project resolution is generally expressed as meters / pixel because the projection and coordinate reference systems used by this project, including EPSG:900913, UTM Zones, and ESRI:102009 are in meters. 
- When available and provider source map data provider resolution data will be used to usable 'zoom levels'
  - The native scale of FAA VFR sectional charts is 1:500000
    - Per, ADR-001 when (re)projected to ESRI:102009, the xy resolution of a pixel of the sectional chart data is approximately 40m/pixel
  - The native scale of FAA Terminal Area charts is 1:250000
    - Per, ADR-001 when (re)projected to ESRI:102009, the xy resolution of a pixel of the TAC data is approximately 20m/pixel
- When processing sectional and terminal area charts we will provide tiles that enable zoom levels at the following resolutions, assuming square pixel cells: 20m/pixel, 40m/pixel, 80m/pixel, 160m/pixel, 320m/pixel, 640m/pixel, 1280m/pixel, 2560m/pixel
- We want to, optionally, integrate this map's zoom levels with other map data sources which are often available in  ESPG:900913. Our zoom levels will be one less than those used by 256x256 tiles because of ADR-003 and our 512x512 tiles. To that end when discussing google web mercator style, **0-indexed** zoom levels we will correlate the above resolutions to the following zoom levels,
  - 20m/pixel: zoom level 12
  - 40m/pixel: zoom level 11
  - etc...
  - 2560m/pixel: zoom level 5

### Impacts 

This decision will impact map tile generation including how many different resolutions of data are produced. The resolutions that data is scaled to. The configuration of client code to process map tiles.

### Reasoning

As we move past the first milestone, we need a way of definig shared zoom definitions across map layers and different input sources. Furthermore, because we are not necessarily using ESPG:900913, we need a more precise way of describing the underlying scaling of raster map data *we* process; yet, we also still need a way of correlating our decision to other commonly available map data. This decision attempts to cover what's need to drive tile pyramid generation from FAA VFR chart data (section and terminal area chart) 

### External references for additional information

- [ESRI ArcGIS pro information on cell size and resolution](https://pro.arcgis.com/en/pro-app/latest/help/analysis/spatial-analyst/performing-analysis/cell-size-and-resampling-in-analysis.htm)
- [ESRI Map information on cell size and rasters](https://desktop.arcgis.com/en/arcmap/latest/manage-data/raster-and-images/cell-size-of-raster-data.htm)
- [Openstreet map zoom levels](https://wiki.openstreetmap.org/wiki/Zoom_levels)
- [Azure maps zoom levels and tile grid information](https://learn.microsoft.com/en-us/azure/azure-maps/zoom-levels-and-tile-grid?tabs=csharp)
- [ArcGIS online world street map server scale and resolutions](https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer)

### Corollaries and Examples

- Not all map data will be available at all zoom levels
- Many web map providers, open or closed source, function based on a web mercator based scheme. The above links to Openstreet maps and azure maps are two such examples. The above 'zoom levels' are scaled to roughly align with the resolution of openstreet map data, but are unlikely to be perfect.
- Note above that we support overscaling the sectional VFR charts from a native resolution of ~40m/pixel to ~20m/pixel. This is done to enable easy integration of VFR terminal area charts (native resolution of 20m/pixel) as overlay on top of sectional charts. It is anticipated that the sectional charts will be blocky and may have visual artifacts when overzoomed.

### Updates

- 2026-02-03: tilemaker now emits zero-based `z` indices aligned to the
  resolution list (coarsest resolution -> `z=0`, finest -> `z=N-1`). The
  tile configuration output no longer includes ADR-005 zoom numbers; the
  ADR-005 zoom mapping remains a conceptual reference for correlating
  resolutions to common web-mercator zoom conventions.
