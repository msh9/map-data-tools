## ADR-001 Coordinate Reference Systems

### Decision:

The mapping system wil use multiple projected coordinate reference systems (CRS) due to the projects varying underlying data sources. In particular,

- Maps and charts will be reprojected in a north american focus lambert conformal conic projection. We will use ESRI:102009.
- The source data, ie the underlying maps and charts, used by the system will determine the viewable extent of the systems user interfaces
- The viewing client will assume use of the ESRI:102009 projection for viewing and will limit it's viewable extent to data published by the tile system
- User input and output will be performed using WGS84 latitude and longitude.

### Impacts 

This decision will impact map tile generation, serving, and rendering library choices; primarily necessitating use of software that can handle custom coordinate reference systems and render CRS besides web mercator. 

### Reasoning

FAA VFR and terminal charts use a lambert conformal conic projection for improved east-west accuracy and preservation of map feature correlation to real world feature correlation. Unfortunately, each published chart has its own paralles, resulting in each VFR chart's projection being slightly different. In order to generate a scrollable map which we can perform calculations, like distance, against we need to reproject the underlying charts into a consistent CRS. 

Additionally, we will be combining other sources of data with the FAA's charts. For example, the FAA's navigation aid location data is published in EPSG:4326, WGS 84 latitude and longitude. Similarly, USGS topographical data is published using Universal Tranverse Mercator zones. We need consistant CRS in order to combine these data sets.


### Corollaries and Examples

- The client viewer will require code that translates the current CRS to WGS84 coordinate in order for the user to read out a point location in latitude and longitude.
- Use of ESRI:102009, *now*, does not rule out use of Mercator projections like EPSG:3395 later. In fact, in the future, we'll likely generate and enable user interaction via both.