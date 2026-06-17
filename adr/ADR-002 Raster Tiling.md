## ADR-002 Raster Tiling

The following is to be used in conjunction with ADR-003 and ADR-005. Together with other, likely not yet written ADRs, these specify how raster and eventually vector map data will be handled in order to enable efficient scrollable maps.

### Decision:

- Raster data will be made available for client use with a custom XYZ tiling scheme. The resolutions and zoom levels are defined in ADR-005 and aim to provide reasonable defaults for aviation and aviation adjacent uses while maintain compatibilty for non-FAA data sources.
- Tiling of data that *we* produce will be done based on ESRI:102009, per ADR-001. This means that XY coordinates will based on a square 512px tiles (per ADR-003) cut from a lambert conformal conic projection of north america. For each set of tiles the ZXY scheme will be based on the source data's extent (ie we follow common processing rules for generating ZXY tiles where the origin is the "top-left" corner of the source.)


### Impacts 

- Not all, in fact, many X-Y tiles will be missing. For example, it's expected that all X positions over the pacific and atlantic oceans in the projection will not have tiles. This is OK and anticipated. It is expected that the extent of the projection will be much larger than the actual map data.
- Additionally, we do not expect to generate all "zoom levels" or resolutions for most, if not all, of our data sets. Google maps style ZXY tile supports zooming out until the entire map is contained in a single tile. This is not currently useful for our applications and would be waste of space. 

### Reasoning

We need a standardized way of producing XYZ tile pyramids as we start incorporating multiple backing data sources.

### Corollaries and Examples

- There is as-yet unsolved problem of what this custom tiling approach means for integrating with web mercator based tile pyramids. We will solve that problem at a later date.
- This ADR does not restrict Flyer Map applications to only using raster tiled data. It only covers, when handling raster tiles, how to approach handling them.

### Updates

- 2026-02-04: Removing the requirement to use the full extent of ESRI:102009 as the origin for tiling XY. This was based on an incomplete understanding ZXY tiling. This update instead merely requires that XY tiling occur based on the extent of the tiled data projected in ESRI:102009.