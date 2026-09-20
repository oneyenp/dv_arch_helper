# dv_arch_helper

`dv_arch_helper` is a small collection of design-verification architecture utilities focused on extracting DUT interface information and preparing it for downstream verification workflows.

The repository currently contains:

- an RTL structure parser that extracts DUT port declarations, comment groups, inline comments, parameters, FSM candidates, registers, and module instantiations;
- a design proposal for extending the flow with Synopsys Verdi Python NPI (`pynpi`) so that elaborated interface information can be obtained directly from `simv.daidir`.

## Repository layout

```text
dv_arch_helper/
├── README.md
├── docs/
│   └── python_npi_dut_interface_extraction.md
└── scripts/
    └── parse_rtl_structure_v2.py
```

## Current RTL parser

`scripts/parse_rtl_structure_v2.py` supports both common ANSI-style ports and classic/non-ANSI port declarations in the module body.

Example source:

```verilog
//------------------- producer <-> consumer
//CHANNEL_A
//stream
input            stream_start;
input            stream_valid; // valid indicator
input      [5:0] stream_meta;
input    [383:0] stream_payload;
```

The parser preserves the standalone comment block as a signal-group comment and keeps an inline `//` comment on the corresponding signal.

### JSON output

```bash
python3 scripts/parse_rtl_structure_v2.py rtl/top.v
```

### CSV output

```bash
python3 scripts/parse_rtl_structure_v2.py \
    rtl/top.v \
    --format csv \
    --module my_dut \
    -o dut_ports.csv
```

The port table uses these columns:

```text
port_type,width,range,sig_name,comment
```

Example:

```csv
port_type,width,range,sig_name,comment
,,,,------------------- producer <-> consumer | CHANNEL_A | stream
input,1,,stream_start,
input,1,,stream_valid,valid indicator
input,6,[5:0],stream_meta,
input,384,[383:0],stream_payload,
```

CSV output intentionally contains no blank rows.

## Planned Python NPI flow

See:

[`docs/python_npi_dut_interface_extraction.md`](docs/python_npi_dut_interface_extraction.md)

The planned flow uses the elaborated Verdi design database as the authoritative structural source while keeping RTL parsing for source-level semantic information.

The intended ownership model is:

| Information | Source |
|---|---|
| DUT instance and elaborated port existence | Python NPI |
| `input` / `output` / `inout` direction | Python NPI |
| Effective width and range | Python NPI |
| Effective parameter values | Python NPI when available |
| Source parameter names/defaults | RTL source |
| Original parameterized range | RTL source |
| Signal comments and comment groups | RTL source |

For a parameterized port such as:

```systemverilog
parameter WIDTH = 32;
input [WIDTH-1:0] data_i;
```

with an instance override:

```systemverilog
.WIDTH(128)
```

the intended output preserves both views:

```text
source_range   = [WIDTH-1:0]
default        = 32
override       = 128
effective      = 128
range          = [127:0]
width          = 128
```

## Roadmap

### V1.0 — DUT interface inventory

- Python NPI runtime setup
- DUT scope lookup
- input/output/inout enumeration
- elaborated width/range extraction
- parameter default/effective/override representation
- RTL comment merge
- JSON and optional CSV output

### V1.1 — Static connectivity

- upstream driver tracing for DUT inputs
- downstream load tracing for DUT outputs
- bidirectional tracing for `inout`
- sibling instance/port discovery
- parent-port discovery
- multi-load support

### V1.2 — Clock-domain analysis

- Python NPI clock-domain extraction
- optional SDC input
- `src_clock[]`
- `dst_clock[]`
- same-domain / CDC classification

### V1.3 — Interface inference

Combine source comments, naming patterns, connectivity, and clock-domain consistency to infer higher-level interfaces.

## Requirements

The current RTL parser requires only Python 3 and the standard library.

The planned NPI implementation will additionally require a Synopsys Verdi installation with Python NPI available under:

```text
$VERDI_HOME/share/NPI/python
```

The exact installed Python NPI API must be inspected before implementation; the flow should not assume that Tcl NPI command names map directly to Python bindings.

## Design principles

- Treat elaborated design data as authoritative for structural facts.
- Preserve source-level intent such as parameter names and original ranges.
- Do not invent values when NPI information is unavailable.
- Keep raw extraction separate from connectivity, clock analysis, and interface inference.
- Load the design database once and batch all NPI queries in one session.
- Keep JSON as the primary machine-readable representation and CSV as an optional human-readable report.
