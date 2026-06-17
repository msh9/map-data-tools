## ADR-006 Data Processing Responsibilities

The following begins to (but is not all inclusive) clarify how we segregate responsibilities between applications in this project and aids us when making decisions about where new applications will reside.

### Decision:

- To the extent that is reasonably possible we want to decouple specialized processing of propriatary formats from processing of broadly comptable data. In practice this means that we will create separate modules and in many cases separate applications, like utilities, for parsing specialized formats in more generically reusuable intermediary formats. An example of this is parsing FAA digital obstable files in geojson is handled by a utility for parsing third party data. That utility is separate from the tools and software that handle map tiling, processing of geojson, pmtiles, etc. 
- This decision also means that to the extent possible we want to use common used, well defined, interchange formats for intermediate and stored data. For example, we process obstable data or map masks, we use geojson instead of a custom format. 


### Impacts

- This mostly impacts how we process data from the FAA which publishes aeronautical data in a wide variety of CSV and other delimited formats. It means that to the extent that it is reasonable will separate parsing of proprietary FAA formats from downstream geospatial information processing. It is important to note the use of the word **reasonable** in this context. Occasionally, it may not make sense to separate processing. In the instance of chart geotiffs, it does **not** make sense to break out processing of the sidecar htm metadata file. We are focused on cases where there is a clear intermediate format.
- Another impact of this is breaking apart processing of vector and raster data into multiple steps. For example, we might preprocess, using `gdal`, FAA raster charts by converting them into RGB images, reprojecting, clipping them, and then saving as an intermediate losslessly compressed output. This separates data preparation from output formating and output file organization duties. 

### Reasoning

This project is both a mapping application and data application with multiple potential downstream uses ranging from real-world flight planning to aviation adjacent gaming. We want to separate propriatary data processing from general geospatial processing in order to make our work reusuable and to encourage modular architecture. 

### Updates

- 2026-02-24: Updated impacts to note use of intermediate chart processing artifacts