# Not_Relevant/

Code and artifacts that are **no longer part of the active sCure Box software**.
Nothing here is built, linted, tested, deployed, or imported by `src/`, `server/`, `io_controller/`, `cloud/` or `scripts/`.
Files were moved (with `git mv`, history preserved) during the 2026-08 cleanup after verifying no active reference remained;
each subfolder README lists the original paths and why the files were parked.

| Folder | Contents |
|---|---|
| `legacy/` | Superseded standalone drivers, Tk dashboards, old README/requirements from `io_controller/`, hardware reference sheets |
| `unused/` | Frontend components/assets with zero importers |
| `prototypes/` | Dead-end UI prototypes (e.g. the standalone material editor page replaced by `CsvBuilderModal`) |
| `development-tools/` | Bench-analysis scripts, one-off tooling outputs, packaged artifacts (zips, .scu) |
| `old-implementations/` | Earlier implementations of live functionality (e.g. the C++ pybind11 hardware driver) |

If something here turns out to be needed, move it back and wire it in deliberately.
