# Dia capability inventory

Audit: 2026-09-19, source baseline `77fe10bc0`. The exact runtime types, versions,
sheet labels and memberships are in [mcp-runtime-inventory.json](mcp-runtime-inventory.json).
It is a reproducible observation of the built Ubuntu 26 worker, not an allowlist
or a guarantee about other installations. `list_sheets` / `list_object_types`
provide the current worker inventory; never read this snapshot as runtime truth.

## Three different capability sets

| Set | Verified extent | Meaning |
| --- | --- | --- |
| Repository source | 38 sheet files; 783 shape files; 17 object module directories in `objects/meson.build` | Build inputs, including compiled factories, custom/custom-line loaders and palette definitions. Files need not equal loaded types. |
| Native worker runtime | 38 sheets; 887 registered types; 891 palette entries; no unavailable returned entry | Includes duplicate palette entries/variants, aliases and types outside sheets. Factory registration is not proof that every factory can be instantiated safely with default arguments. |
| MCP editing contract | 13 node types; 4 connector types; 9 snapshot tools + 2 discovery tools + 9 live read tools | Creation is still bounded to the listed types. Every native type can be discovered; arbitrary properties/creation and live GUI editing are future work. |

Dia supports mixed diagrams. Names in this table are palettes and visual languages,
not a mandatory document type. A symbol catalog does not promise electrical,
hydraulic, civil, network or other engineering simulation/validation.

## Complete loaded sheet inventory

Descriptions below come from Dia, including human-readable distinctions that
cannot safely be reconstructed from type prefixes. Counts are palette entries.

| Sheet | Entries | Runtime description |
| --- | ---: | --- |
| AADL | 11 | AADL Shapes |
| Assorted | 41 | An Assorted Collection of Polygons, Beziergons and other Miscellaneous Geometric Shapes |
| BPMN | 42 | Business Process Modeling Notation |
| ChemEng | 52 | Collection for chemical engineering |
| Chronogram | 2 | Objects to design chronogram charts |
| Circuit | 32 | Components for circuit diagrams |
| Cisco — Computer | 49 | Computer shapes by Cisco |
| Cisco — Miscellaneous | 50 | Miscellaneous shapes by Cisco |
| Cisco — Network | 99 | Network shapes by Cisco |
| Cisco — Switch | 71 | Router and switch shapes by Cisco |
| Cisco — Telephony | 54 | Telephony shapes by Cisco |
| Civil | 27 | Civil Engineering Components |
| Cybernetics | 30 | Elements of cybernetic circuits |
| Database | 3 | Editor for Database Table Relation Diagrams |
| EDPC | 14 | Objects to draw event-driven process chains |
| ER | 5 | Editor for Entity Relations Diagrams |
| Electric | 15 | Components for electric circuits |
| FS | 3 | Editor for Function Structure Diagrams. |
| Flowchart | 29 | Objects to draw flowcharts |
| GRAFCET | 12 | Objects to design GRAFCET charts |
| Gane and Sarson | 4 | Gane and Sarson DFD |
| Jigsaw | 16 | Pieces of a jigsaw |
| Ladder | 12 | Components for LADDER circuits |
| Lights | 13 | Objects to design simple lighting plots |
| Logic | 9 | Boolean Logic |
| MSE | 6 | U.S. Army Mobile Subscriber Equipment Components |
| Map, Isometric | 24 | Isometric Directional Map Shapes |
| Miscellaneous | 10 | Miscellaneous Shapes |
| Network | 37 | Objects to design network diagrams with |
| Pneumatic/Hydraulic | 20 | Components for pneumatic and hydraulic circuits |
| RE-Jackson | 6 | Objects to design Jackson diagrams |
| RE-KAOS | 21 | Objects to design KAOS diagrams |
| RE-i* | 14 | Objects to design i* diagrams |
| SADT/IDEF0 | 3 | Objects to design SADT diagrams |
| SDL | 17 | Specification and Description Language. |
| Shape Design | 2 | Design Dia objects with individual connection points |
| Sybase | 6 | Objects to design Sybase replication domain diagrams with |
| UML | 30 | Editor for UML Static Structure Diagrams |

## Registered types without a sheet entry

These 39 names are still part of runtime discovery. Standard toolbox objects,
aliases and legacy factories explain why sheet enumeration alone is incomplete:

`Cisco - Communications server`, `Cisco - DPT`, `Cisco - Dot-Dot`, `Cisco - Gigabit Switch Router (ATM Tag)`, `Cisco - Layer 3 Switch`, `Cisco - Man/Woman`, `Cisco - PC Man left`, `Cisco - PIX Firewall Left`, `Cisco - Router in building`, `Cisco - SVX (interchangeable with End office)`, `Cisco - Sitting Woman right`, `Cisco - Telecommuter house/router`, `Cisco - Video Camera right`, `Cisco - Voice switch 2`, `Cisco - Workstation`, `Contact - if`, `Contact - ifnot`, `Contact - lamp`, `Contact - relay`, `GRAFCET - Vector`, `Geometric - Isoceles Triangle`, `Group`, `RedCar`, `Standard - Arc`, `Standard - BezierLine`, `Standard - Beziergon`, `Standard - Box`, `Standard - Bus`, `Standard - Ellipse`, `Standard - Image`, `Standard - Line`, `Standard - Outline`, `Standard - Path`, `Standard - PolyLine`, `Standard - Polygon`, `Standard - Text`, `Standard - ZigZagLine`, `UML - Objet`, `chemeng - pnuemv`.

The JSON companion contains **all 887 type names and native type versions**, not
only representative types. Sheet entry creation data is not exposed by PyDia;
multiple labels for a factory must be retained without pretending to distinguish
all native variants. `Group` also illustrates that registry membership is not a
guarantee of a normal zero-configuration factory operation.

## Complete current MCP editing inventory

| Area | Implemented behavior / exact types | Boundaries |
| --- | --- | --- |
| Documents | Create named empty session, inspect full logical state/geometry, close session | No MCP-triggered open/import, Save/Save As or persistence recovery. M2 separately lists live GUI documents. |
| Flowchart nodes | `Flowchart - Box`, `Flowchart - Ellipse`, `Flowchart - Diamond` | Text and dimensions; no semantic branch/termination validation. |
| UML node | `UML - Class` | Name, stereotype, abstract, typed attributes/methods/parameters and width; height derives from contents. |
| Electrical nodes | `Electric - contact_o`, `contact_f`, `relay`, `lamp`, `connpoint` (full `Electric - ` prefix for each) | Visual native symbols, aspect-preserving size, flips, text/auxiliary labels; no circuit validation. |
| Pneumatic nodes | `Pneum - DEJack`, `dist52`, `presspn`, `drain` (full `Pneum - ` prefix) | Same visual-symbol support; no physical simulation. |
| Generic connectors | `Standard - Line`, `Standard - ZigZagLine` | Attached endpoint handles, optional end arrow, semantic compass ports or inspected indices. |
| UML connectors | `UML - Generalization`, `UML - Association` | Two class endpoints, native name/label; source of generalization is superclass. No dedicated aggregation/composition/dependency/realization tool. |
| Edits | Move node; replace supported text/dimensions/UML properties/flips | Full materialization on each call; no delete, disconnect, arbitrary property change, resize handles, duplicate, retype or batching. |
| Inspection | IDs, revision, node fields, bounds, auxiliary label bounds, point indices/positions/directions, chosen ports, connector endpoints | Session data, not arbitrary native document; no full handles, properties, grouping, layer/selection or graph queries. |
| Discovery (new) | Native sheets/types, labels, membership, type versions, pagination, creatable marker | Read-only worker inventory. No default property schema or icon blobs. M2 reads GUI objects and returns the actual Dia version. |
| Export | `.dia`, `.svg`, `.png` | Native serialization/renderers, safe basename publication and validation. Other native formats are not exposed by MCP. |
| Live inspection (M2) | GUI documents, layers, selection, arbitrary objects, native connections and conservative properties | Read-only, opt-in, versioned local socket; no history/layout/write commands. |
| MCP resources/prompts | None | Tools only. |

ER/database, network, civil, logic, telecom, cybernetics, chemistry, process,
organizational (using generic shapes) and other domains can be drawn in standalone
Dia. Most native objects in these families are **discoverable but not MCP-creatable**
today. This is an architectural gap, not missing support in Dia itself.

## Native operations and export beyond MCP

Standalone Dia supplies layer visibility/order, selection, grouping, object
properties and text, copy/paste, alignment/distribution, undo/redo, native load/save,
printing and renderer/plugin exports. Compiled object families include AADL,
chronograms, Database, ER, flowchart, FS, GRAFCET, i*, Jackson, KAOS, Misc,
network, SADT, standard and UML, alongside custom shapes/lines.

The normal installed startup also registers Python exporters (code generation,
DOT, SVG and others). The MCP's dedicated startup deliberately does not load those
Python startup plugins. Therefore normal `dia --list-filters` and the MCP worker
can have different inventories; the three advertised MCP formats are the stable
editing contract. Export availability must be probed in the same startup mode
before widening it. See the regeneration commands in [development](mcp-development.md).

The observed native CLI has 27 export-filter entries under the dedicated MCP
startup: AVIF, BMP, CGM, XSL transformation (`code`), CairoScript, Dia, DXF, EPS,
Xfig, ICO, JPEG, MetaPost, PDF, HPGL, three PNG filters (`cairo-png`,
`cairo-alpha-png`, `pixbuf-png`), PostScript, Dia shape, two SVG filters
(`cairo-svg`, `dia-svg`), two TeX filters (`pgf-tex`, `pstricks-tex`), TIFF, Visio
XML, WebP and WPG. Normal startup reports 37 entries: it additionally registers
Python Imagemap, C++, DOT, Java, JavaScript, Pascal, PHP, Python, plain SVG and
compressed SVG exporters. This is filter registration, not an export test for
every format; the MCP integration tests exercise only Dia/SVG/PNG.

## Test coverage and missing coverage

Existing tests cover all 13 allowlisted node types, connections, UML structured
members/relationships, electrical/pneumatic terminals/flips, exported native XML,
SVG/PNG validation, reload, failed edits/publication and actual MCP stdio. The new
suite covers discovery across UML/flowchart/Database/ER/Network/Electric, duplicate
palette labels, orphan factories, missing sheets, pagination, invalid metadata,
custom shape/sheet discovery and freshness after a sheet is removed.

Discovery tests do not establish editing correctness for ER/network/custom shapes.
M2 adds live document/selection reads and conservative properties, with actual GUI
and stdio tests for UML, flowchart, ER, database, Cisco/network, electrical and a
custom shape. Real native Delete/Undo/Redo and File/Quit are exercised from trusted
GUI-side test code under Xvfb and real Wayland. There are still no MCP history/write
commands, unknown-type creation or database/network semantic validation.
