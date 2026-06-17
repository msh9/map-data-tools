  ## Must-follow project rules
  - Follow `./SPECIFICATION.md` 
  - Follow ADRs in `../../adr/` (especially CRS + tile encoding + language choices).
  - *Read* the README.md file instructions on how to run the dev server, test, and lint.

  ## Key technical decisions (do not deviate)
  - CRS: use a consistent lambert conformal conic projection. See `../../adr/ADR-001 CRS.md`.
  - Tiles: See `../../adr/ADR-003 Tile Encoding.md`.
  - URL layout: tiles addressed as `z/x/y`; the tile config defines grid (origin + resolutions + extent). See `./SPECIFICATION.md`.

  ## Language + dependency policy
  - Use Python with the minimal set of libraries needed. See `../../adr/ADR-004 Language Choices`.
  - Use a Python virtual environment when working on this project.
  - Ensure dependent libraries are managed within the project environment.
  - Do not add third-party deps just to avoid small amounts of code (< ~100 LOC); prefer simple local code + tests.
