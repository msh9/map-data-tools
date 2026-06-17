## ADR-003 Raster/Image Encoding
Note ADR-003 previoulsy erronously referred to itself as tile encoding.

### Decision:

- Encode image raster tiles as avif or webp, using 512x512 sizing. The pipeline should target 20% quality AVIF or 40% quality webp for encoding raster image tiles. **This decision do not impact non-image data which should be compressed using alternate means**.
- Generally tiles should contain some kind of data and where possibly we want to avoid generating tiles or images with no data. There is a **important** exception to this with data edges or sparse data sets where tiles will contain some pixels with data and some pixels which should be transparent due to there being no data. This is normal, expected, and needed for rendering.
- Intermediate raster formats that are used in multiple downstream processing steps should be stored with high effort lossless compression such as jpegxl with effort 7 or greater or ZSTD with level 18 or higher.
- For non-image raster data (e.g., slope masks), use PNG with lossless encoding of two 1-byte channels (grayscale + alpha). This preserves data fidelity for non-photographic content while remaining browser-compatible.

### Impacts

The choice of encoding impacts the use of client code and rendering pipeline. 

### Reasoning

The vast majority (\>90%) of web (brower) clients on mobile and desktop support avif and webp image encoding. Additionally, any gamified use of these charts will be within a custom client that can include avif support as needed. Given this context, we should take advantage of avif's superior compression to deliver smaller tiles. We will use 512x512 tiles as it is still a common map tile size.

We additionally call out the use of webp for its faster encoding time. During development it may be useful to use a faster codec like webp. It's anticipated that only avif will be used in production.

Finally, regarding intermediate formats, we expect that intermediate will only be used internally therefore we can used lessor support compression like jpegxl.

### Updates

- 2026-03-31: Added guidance for non-image raster data encoding using PNG with LA channels.
- 2026-03-31: Updated title and decision language to clarify that this ADR applies to image raster data alone.
- 2026-02-04: Updated language around transparency to indicate that pixels in generated tiles/data *may* be transparent in cases where the edge of a data set is being rendered. The intent of the original statement was to indicate that we should not render or waste space with complete empty tiles.
- 2026-02-24: Added language regarding intermediate formats