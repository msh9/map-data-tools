## ADR-007 FAA Chart Organization

The following describes how we organize FAA chart data for processing and downstream consumption.

### Decision:

- FAA sectional charts, terminal area charts, and other aviation data will be organized by geographic region. For example, TAC and section charts for Alaska are organized into output layers (pmtiles, ZXY directories, etc) contain just data for Alaska. 
- At time of writing and most recent update (2026-02-24) we will use the following geographic names as needed,
    - alaska: denotes the state of Alaska and surrounding region
    - caribbean: US caribbean islands and part of Florida
    - west: western continental US states
    - mountain: mountain continental US states
    - central: central continental US states
    - north_east: north eastern continental US states
    - south_east: south eastern continental US states
    - pacific: Pacific islands
    - conus: entire continental US, which can in turn be mapped to union of 'west', 'mountain', 'central', 'north_east', and 'south_east'. We define 'conus' for use with sparse datasets that we want to combine into a single output, for example, all continental US terminal area charts.
- The mapping from section and terminal area chart to geographic is static and defined, currently, in 'third-party-static-data/'. Please see the README in that directory for further information.

### Impacts

The impacts how we process FAA for storage and output. In particular this decision determines the number of files and their corresponding source content when generating geotiffs, pmtiles, or similar archives for consumption.

### Reasoning

Our applications combine FAA raster information from multiple sources into single files. The output files are generally, multiple gigibytes even with webp, jpegxl, or avif compression. In order to keep individual files to a reasonable size, say 5 < GB, we need to split our data outputs.

### Corollaries

Depending on dataset sizes we will likely use similar geographic divisions in the future for splitting, other, non FAA derived data sources. 