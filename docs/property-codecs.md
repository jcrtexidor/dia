# Native property surface audit (M8)

The existing live scalar gate remains closed to compound values and resources.
`dia_mcp.property_policy.classify_property(descriptor)` performs no native calls:
it returns `classification`, `readable`, `editable`, a reason and source evidence.
`editable` means a candidate permitted by the descriptor/type gate; the native
transaction still validates enum membership, numeric ranges, string/number
limits, object membership and generation. This audit does **not** prove that
individual plugins accept arbitrary values or that setters round-trip.

## Measured installation

The checked-in [machine-readable inventory](property-inventory.json) identifies
the immutable image, binary hash, source hashes, audit timestamp, every attempted
factory, descriptor flags, worker outcomes and classified descriptor counts.
The input is the installed `/opt/dia/bin/dia` in image
`sha256:92465cb32fd10af263110b3b146ab3c3186b82af391556550cdc501b4e03e804`.

| Observation | Count |
| --- | ---: |
| Registered types / factory attempts | 887 |
| Successful ordinary factory creations | 886 |
| Factory failures | 1 |
| Descriptors from successful ordinary factories | 13,216 |
| Distinct kinds from ordinary factories | 34 |
| Truncated descriptor lists | 0 |
| Abnormal worker exits | 0 |
| Additional group probe descriptors | 17 |

`Group` is registered but has no ordinary factory operations (`lib/group.c`:
`group_type.ops = NULL`). Its normal `.create()` raises
`RuntimeError: Type has no ops!?`. This is reported as a factory failure, not
silently removed from the denominator. A separate trusted disposable probe uses
`dia.group_create([Standard - Box])`; it returns 17 descriptors including
`matrix`. Group descriptors depend on member types, so that probe is not an
exhaustive union of all possible group properties. There are 35 observed kinds
when this supplemental probe is included.

Ordinary factory descriptor classifications:

| Classification | Count |
| --- | ---: |
| `safe_read_write` | 4,154 |
| `safe_read_only` | 2,488 |
| `requires_domain_codec` | 6,295 |
| `requires_resource_policy` | 193 |
| `unsupported` | 86 |
| `unknown` | 0 |

These are descriptor **occurrences**, not unique names or proven setter cases.
The group probe is kept separate and is excluded from those totals.

## Policy and native evidence

All `PROP_TYPE_*` strings defined in `lib/properties.h` have explicit policy;
portable tests fail if a future native definition is left unclassified. Unknown
third-party kinds fail closed. Source links below describe the native
implementation; an available legacy PyDia getter/setter is not permission to
expose it through live MCP.

| Native kind(s) | Default policy for valid non-load-only descriptors | Source and required interpretation |
| --- | --- | --- |
| `bool`, `int`, `enum` | read/write when visible, otherwise read-only | `lib/prop_inttypes.c`; `pydia-live.c:set_properties` validates native integer width and descriptor enum/range membership. Enum choices are not exported by the descriptor reader. Legacy bool getter returns an integer. |
| `real`, `length`, `fontsize` | read/write when visible, otherwise read-only | `lib/prop_geomtypes.c`; finite values, native numeric bounds and descriptor ranges remain authoritative. |
| `string` | read/write when visible, otherwise read-only | `lib/prop_text.c`; existing bounded live string policy only, not permission to treat a resource property as a string. |
| `text` | read/write including nonvisible descriptors | `lib/prop_text.c`; native text exception; live reads extract the text string, not the entire text/font/position object. |
| `intarray`, `enumarray`, `stringlist` | requires domain codec | `lib/prop_inttypes.c`, `lib/prop_text.c`; require bounded lengths and element validation. Enum arrays need per-element enum semantics. |
| `sarray`, `darray` | requires domain codec | `lib/prop_sdarray.c`; heterogeneous/nested record layouts depend on native descriptors. UML attributes/operations/templates and Database attributes are not interchangeable. |
| `dict` | requires domain codec | `lib/prop_dict.c`; bounded key/value schema and replacement/merge semantics need an explicit contract. |
| `point`, `pointarray`, `bezpoint`, `bezpointarray`, `rect`, `endpoints`, `connpoint_line` | requires domain codec | `lib/prop_geomtypes.c`; require finite geometry, bounded arrays, Bezier discriminants and object-specific update/connection invariants. A scalar position setter is not equivalent to native move. |
| `matrix` | requires domain codec | `lib/prop_matrix.c`; requires finite transform encoding and group/member semantics. Observed only in the supplemental group probe. |
| `colour`, `linestyle`, `arrow` | requires domain codec | `lib/prop_attr.c`; structured color/line/arrow values need bounded, typed encodings, enum validation and dimensions. They are not enabled by the scalar gate. |
| `font` | requires resource policy | `lib/prop_attr.c`; native font objects and ownership/font availability are not portable string values. |
| `file` | requires resource policy | `lib/prop_text.c`; legacy string conversion does not supply path authorization, workspace boundaries or file lifecycle. |
| `pixbuf`, `pattern` | requires resource policy | `lib/prop_pixbuf.c`, `lib/prop_pattern.c`; native image/capsule/pattern resources require explicit ownership and bounded decoding. No image pixels or resources were fetched. |
| `char`, `multistring` | unsupported | Native implementations exist in `lib/prop_inttypes.c` / `lib/prop_text.c`, but these kinds are outside the current live scalar contract. |
| `invalid`, `noop`, `unimplemented` | unsupported | `lib/prop_basic.c`; no live value codec. |
| `static`, `button`, `list`, `nb_begin`, `nb_end`, `nb_page`, `mc_begin`, `mc_end`, `mc_col`, `f_begin`, `f_end` | unsupported | `lib/prop_widgets.c`; property UI/control descriptors, not ordinary live data values. |
| `object`, `objectref`, `image` | requires resource policy, reserved defensive cases | Not native `PROP_TYPE_*` definitions or observed descriptor kinds in this installation. No generic object-reference codec is claimed. Native connectivity comes from inspected handle/connection APIs, never serializing C pointers. |
| Any other kind | unknown | No access or inferred codec. |

Policy precedence is deliberate: missing/invalid flags produce `unknown`;
load-only or widget-only descriptors produce `unsupported` even if their kind
has a scalar codec. Readable nonvisible scalar data is `safe_read_only`, except
native `text`, which is writable without `PROP_FLAG_VISIBLE`.

## Descriptor and source limitations

`Object.property_descriptors(256)` in `plug-ins/python/pydia-object.c` calls
`describe_props` and exports `name`, `type`, `visible`, and `load_only` only. The
last flag combines `PROP_FLAG_LOAD_ONLY | PROP_FLAG_WIDGET_ONLY`; it cannot
identify which of the two was set. It does not expose raw flags, enum choices,
numeric ranges, nested array schemas or resource ownership. Visibility alone
is not a reliable read/write permission.

The audit never invokes `obj.properties[...]`, `.value`, get/set property
operations, save/export, or native transactions. In particular, ordinary PyDia
property lookup fetches native values before `.value`; it cannot be used as a
safe descriptor probe. `plug-ins/python/pydia-property.c:prop_type_map` contains
more legacy conversions than the live gate, including wrappers/tuples/capsules
that have no bounded JSON contract here. Nested array access resolves getters
from record types, so reviewing the outer `darray` name alone cannot establish
that a value is safe to traverse.

One conservative behavioral difference is intentional if this policy is used by
the live reader: scalar load-only/widget-only properties are no longer fetched.
The audit found five such occurrences: `UML - Classicon.type`,
`UML - Implements.name`, `UML - Message.message`, `UML - Node.text`, and
`UML - State.type`. Native writes already rejected these. No setter is expanded.

The inventory covers default-created objects and the tested image only. It does
not certify loaded legacy documents, optional plugins installed later, arbitrary
object state, all possible group unions or all dynamically extended descriptors.

## Reproduction

Run the trusted audit locally inside the existing image; it is not an MCP tool
and is not installed as a GUI plugin. For example, from the repository root:

```sh
docker run --rm --init --network=none --user "$(id -u):$(id -g)" \
  -v "$PWD:/audit" -e PYTHONPATH=/audit/mcp/src \
  -e DIA_PROPERTY_AUDIT_IMAGE=sha256:92465cb32fd10af263110b3b146ab3c3186b82af391556550cdc501b4e03e804 \
  dia-mcp:ubuntu26 xvfb-run -a python /audit/mcp/examples/audit_properties.py \
  --output /audit/docs/property-inventory.json
```

Each worker uses a temporary private home and normal Dia startup, with a trusted
one-shot main-loop callback. Batches default to 32 factories. A worker crash or
timeout triggers isolated one-factory retries; Python exceptions are recorded
per factory. Workers terminate after writing their report, without persisting
objects or touching a user's diagram. The script exits nonzero for any factory
failure or truncated descriptor list; the known Group factory failure therefore
produces exit status 1 while retaining the complete report.
