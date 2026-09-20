# Python NPI DUT Interface Extraction Proposal

## 1. Objective

Build a standalone DUT interface extraction flow based on Synopsys Verdi Python NPI (`pynpi`).

The solution must:

- use Python only
- use the elaborated design database as the authoritative structural source
- support a user-specified DUT hierarchy
- extract all top-level DUT ports
- identify `input`, `output`, and `inout` ports
- obtain elaborated width and range
- preserve source-level parameter expressions
- preserve parameter default values
- report instance-level effective/override values
- optionally merge RTL comments and comment groups
- support JSON output
- optionally support CSV output
- avoid Tcl
- avoid FSDB dependency for static interface extraction

The first version focuses on interface extraction only.

Driver/load connectivity and clock-domain analysis are planned as later stages.

---

## 2. Overall Architecture

```text
                         RTL source (optional)
                                │
                                │
                     source comments / groups
                     parameter declarations
                     original range expressions
                                │
                                ▼
                    parse_rtl_structure_v2.py
                                │
                                │
                                │
simv.daidir                    │
     │                          │
     ▼                          │
Python pynpi                    │
     │                          │
     ├── DUT instance           │
     ├── elaborated ports       │
     ├── direction              │
     ├── effective width        │
     ├── effective range        │
     └── effective parameters   │
     │                          │
     └──────────────┬───────────┘
                    ▼
             interface merge
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
        JSON                 CSV
```

The elaborated design database is the authoritative source for structural facts.

RTL parsing is used only to preserve source-level semantic information.

---

## 3. Data Ownership

### 3.1 NPI is authoritative for

- DUT instance existence
- actual elaborated port list
- port direction
- effective port width
- effective packed range
- full hierarchical signal name
- effective parameter value, when exposed by the installed NPI API

### 3.2 RTL source is authoritative for

- source-level parameter name
- source-level parameter default expression
- original parameterized range expression
- preceding `//` comment blocks
- inline `//` comments
- interface/comment grouping

### 3.3 Merge policy

When NPI and RTL disagree:

```text
port existence       -> NPI
direction            -> NPI
effective width      -> NPI
effective range      -> NPI
effective parameter  -> NPI when available

source range         -> RTL
parameter default    -> RTL
parameter name       -> RTL
comment              -> RTL
comment group        -> RTL
```

The tool must never silently overwrite elaborated NPI facts with source-parser results.

---

## 4. Proposed File Structure

```text
scripts/
├── parse_rtl_structure_v2.py
├── pynpi_runtime.py
├── pynpi_probe.py
├── npi_design.py
├── npi_interface.py
└── extract_dut_interface.py
```

### File responsibilities

| File | Responsibility |
|---|---|
| `parse_rtl_structure_v2.py` | Parse source comments, groups, parameter declarations, and original port range expressions |
| `pynpi_runtime.py` | Configure and manage the Python NPI runtime |
| `pynpi_probe.py` | Inspect the locally installed NPI API before production implementation |
| `npi_design.py` | Reusable design-query helpers |
| `npi_interface.py` | Extract DUT ports and elaborated parameter information |
| `extract_dut_interface.py` | User-facing wrapper that merges NPI and RTL information |

---

## 5. Python NPI Runtime

The runtime layer should:

1. require `VERDI_HOME`
2. locate:

```text
$VERDI_HOME/share/NPI/python
```

3. append the directory to `sys.path`
4. import the installed `pynpi` package
5. initialize NPI
6. load the requested `simv.daidir`
7. execute all queries in one design session
8. guarantee cleanup with `npisys.end()`

The design database must be loaded only once per invocation.

Do not start a new NPI process per signal or per port.

---

## 6. NPI API Discovery

The exact Python NPI API must not be guessed.

Before production implementation, inspect:

```text
$VERDI_HOME/share/NPI/python/pynpi/
```

The probe stage should determine the installed APIs for:

- hierarchical instance lookup
- instance handles
- port iteration
- port direction
- packed range
- signal width
- full hierarchical name
- parameter iteration
- effective parameter values
- parameter assignment/override metadata

A dedicated probe script should be provided:

```bash
python3 pynpi_probe.py \
    --dbdir simv.daidir \
    --scope tb_top.u_dut
```

The probe is a development/diagnostic tool only and must not be part of normal report output.

---

## 7. DUT Interface Extraction

### 7.1 Input

Required:

```text
--dbdir <simv.daidir>
--scope <DUT hierarchical instance>
```

Optional:

```text
--format json|csv
--output <file>
--rtl <RTL source file>
```

Example:

```bash
python3 npi_interface.py \
    --dbdir simv.daidir \
    --scope tb_top.u_dut
```

### 7.2 Required port information

For every top-level port of the specified DUT instance:

```text
port_type
width
range
sig_name
full_name
comment
```

Supported port directions:

```text
input
output
inout
```

Example internal record:

```json
{
  "port_type": "input",
  "width": 384,
  "range": "[383:0]",
  "sig_name": "stream_payload",
  "full_name": "tb_top.u_dut.stream_payload",
  "comment": ""
}
```

---

## 8. Elaborated Width and Range

The elaborated NPI result is authoritative.

Example source:

```systemverilog
module dut #(
    parameter WIDTH = 32
) (
    input [WIDTH-1:0] data_i
);
```

Instance:

```systemverilog
dut #(
    .WIDTH(128)
) u_dut (...);
```

The expected structural result is:

```text
width = 128
range = [127:0]
```

while the source-level declaration remains:

```text
source_range = [WIDTH-1:0]
```

### Scalar ports

```text
width = 1
range = ""
```

### Complex arrays

For packed/unpacked multidimensional objects:

- preserve whatever structural information the installed NPI API exposes
- do not silently flatten unsupported structures
- report unresolved fields explicitly

---

## 9. Parameter Default / Override / Effective Value

Both source-level and instance-level information must be retained.

### Example

Source:

```systemverilog
module dut #(
    parameter WIDTH = 32
) (
    input [WIDTH-1:0] data_i
);
```

Instance:

```systemverilog
dut #(
    .WIDTH(128)
) u_dut (...);
```

Required semantic representation:

```text
source_range        = [WIDTH-1:0]
parameter_refs      = ["WIDTH"]

WIDTH.default       = 32
WIDTH.override      = 128
WIDTH.effective     = 128
WIDTH.override_status = overridden

range               = [127:0]
width               = 128
```

### Recommended JSON representation

```json
{
  "module_name": "dut",
  "scope": "tb_top.u_dut",

  "parameters": {
    "WIDTH": {
      "default": "32",
      "override": "128",
      "effective": "128",
      "override_status": "overridden"
    }
  },

  "ports": [
    {
      "port_type": "input",
      "width": 128,
      "range": "[127:0]",
      "sig_name": "data_i",
      "full_name": "tb_top.u_dut.data_i",
      "source_range": "[WIDTH-1:0]",
      "parameter_refs": ["WIDTH"],
      "comment": ""
    }
  ]
}
```

Parameter metadata should be stored once at module/instance level rather than duplicated on every port.

---

## 10. Explicit Override Detection

The tool must not define override status only by comparing values.

This is incorrect:

```text
effective != default
```

because this case is still an explicit override:

```systemverilog
parameter WIDTH = 32;

dut #(
    .WIDTH(32)
) u_dut (...);
```

even though:

```text
default   = 32
effective = 32
```

The installed Python NPI API should be checked for explicit parameter-assignment or override metadata.

Supported states should be:

```text
overridden
default
unknown
```

If the local NPI API cannot distinguish an explicit same-value override from the default, the tool must not invent a result.

Example fallback:

```json
{
  "default": "32",
  "effective": "32",
  "override": null,
  "override_status": "unknown"
}
```

---

## 11. Parameter Expressions

The solution must support parameters whose values are not simple integers.

Examples include:

```systemverilog
parameter WIDTH = BASE_WIDTH * 2;
parameter MODE  = "MODE_A";
parameter TYPE  = MY_ENUM;
parameter MASK  = `SOME_MACRO;
```

The tool should preserve textual representations when necessary.

Do not force all parameter values through Python integer evaluation.

The elaborated NPI result remains authoritative for the final port width/range.

---

## 12. Multiple Parameter References

Example:

```systemverilog
parameter LANES = 4;
parameter DW    = 32;

input [LANES*DW-1:0] data;
```

Instance:

```systemverilog
dut #(
    .LANES(8)
) u_dut (...);
```

Expected representation:

```json
{
  "parameters": {
    "LANES": {
      "default": "4",
      "override": "8",
      "effective": "8",
      "override_status": "overridden"
    },
    "DW": {
      "default": "32",
      "override": null,
      "effective": "32",
      "override_status": "default"
    }
  },

  "ports": [
    {
      "sig_name": "data",
      "width": 256,
      "range": "[255:0]",
      "source_range": "[LANES*DW-1:0]",
      "parameter_refs": ["LANES", "DW"]
    }
  ]
}
```

The final width `256` must come from elaborated design information, not from a Python-side re-evaluation of the expression.

---

## 13. RTL Comment Merge

When an RTL source file is provided, the existing parser should supply comments.

### Group comments

Example:

```verilog
//------------------- producer <-> consumer
//CHANNEL_A
//stream
input stream_start;
input stream_valid;
```

The consecutive comment block should be merged into one group:

```text
------------------- producer <-> consumer | CHANNEL_A | stream
```

### Inline comments

Example:

```verilog
input stream_error; // ECRC error indication
```

Result:

```text
comment = "ECRC error indication"
```

### Merge rule

Port records are matched by `sig_name`.

NPI controls structural fields.

RTL only adds source-level semantic information.

---

## 14. CSV Output

CSV is optional.

The first five columns must remain:

```text
port_type,width,range,sig_name,comment
```

Additional columns:

```text
source_range
parameter_refs
parameter_defaults
parameter_overrides
```

Full header:

```csv
port_type,width,range,sig_name,comment,source_range,parameter_refs,parameter_defaults,parameter_overrides
```

Example:

```csv
input,128,[127:0],data_i,,[WIDTH-1:0],WIDTH,WIDTH=32,WIDTH=128
```

No override:

```csv
input,32,[31:0],data_i,,[WIDTH-1:0],WIDTH,WIDTH=32,
```

Multiple parameters:

```csv
input,256,[255:0],data,,[LANES*DW-1:0],"LANES;DW","LANES=4;DW=32","LANES=8"
```

Rules:

- use Python `csv` module
- do not manually concatenate CSV fields
- do not insert blank rows
- use `;` for multiple values inside one field
- preserve comment-only group header rows
- do not insert empty lines between groups

---

## 15. JSON Output

JSON should be the preferred machine-readable format.

Recommended top-level schema:

```json
{
  "scope": "tb_top.u_dut",
  "module_name": "dut",

  "parameters": {},

  "groups": [
    {
      "comment": "producer <-> consumer | CHANNEL_A | stream",
      "ports": []
    }
  ],

  "ports": [],

  "mismatches": {
    "rtl_only_ports": [],
    "npi_only_ports": [],
    "direction_mismatches": [],
    "width_mismatches": [],
    "range_mismatches": [],
    "parameter_mismatches": []
  }
}
```

---

## 16. Mismatch Reporting

The merge stage should explicitly report:

```text
rtl_only_ports
npi_only_ports
direction_mismatches
width_mismatches
range_mismatches
parameter_mismatches
```

Example:

```json
{
  "mismatches": {
    "rtl_only_ports": ["legacy_debug"],
    "npi_only_ports": ["generated_status"],
    "direction_mismatches": [],
    "width_mismatches": [],
    "range_mismatches": [],
    "parameter_mismatches": []
  }
}
```

Mismatch information must not silently alter the elaborated NPI result.

---

## 17. User-Facing Entry Point

The primary command should be:

```bash
python3 extract_dut_interface.py \
    --dbdir simv.daidir \
    --scope tb_top.u_dut \
    --format json
```

NPI-only CSV:

```bash
python3 extract_dut_interface.py \
    --dbdir simv.daidir \
    --scope tb_top.u_dut \
    --format csv \
    --output dut_ports.csv
```

NPI + RTL source information:

```bash
python3 extract_dut_interface.py \
    --dbdir simv.daidir \
    --scope tb_top.u_dut \
    --rtl rtl/dut.sv \
    --format csv \
    --output dut_ports.csv
```

---

## 18. Error Handling

Initialization/design-load failures are fatal.

Examples:

```text
VERDI_HOME missing
pynpi import failed
dbdir invalid
design load failed
DUT scope not found
```

Per-port extraction failures should not terminate the entire report.

Examples:

```text
direction_unknown
range_unknown
width_unknown
parameter_unknown
```

Unknown data should be reported explicitly.

Do not invent values.

---

## 19. Testing Strategy

### 19.1 Pure Python tests

Cover:

- comment-group parsing
- inline comments
- CSV without blank rows
- source range preservation
- parameter reference extraction
- parameter default preservation
- merge priority
- mismatch reporting
- CSV serialization
- JSON serialization

### 19.2 Real NPI smoke design

Use a real elaborated design database containing:

- scalar input
- scalar output
- inout
- vector input
- vector output
- parameterized-width input
- default parameter
- overridden parameter
- same-value explicit override, if detectable

Validate:

```text
scope lookup
port enumeration
direction
width
effective range
full_name
effective parameter
override metadata
```

Undocumented NPI behavior should not be mocked.

---

## 20. Version 1 Scope

Version 1 includes:

```text
DUT scope lookup
input/output/inout enumeration
elaborated width
elaborated range
full hierarchical names
parameter default information
parameter effective values
parameter override information when available
RTL source comments
comment groups
JSON output
CSV output
mismatch reporting
```

Version 1 does not include:

```text
driver/load connectivity
clock-domain extraction
CDC analysis
FSDB analysis
Tcl implementation
```

---

## 21. Future Stage: Python NPI Connectivity

After interface extraction is validated, extend the same loaded design model with static connectivity.

Planned behavior:

```text
DUT input  -> trace upstream driver
DUT output -> trace downstream load
DUT inout  -> trace both
```

The first connectivity stage should identify:

```text
parent net
sibling instance
sibling port
parent port
multiple loads
unconnected ports
```

One-level connectivity should mean logical hierarchy depth, not one NPI object hop.

---

## 22. Future Stage: Clock-Domain Analysis

After connectivity is stable, add Python NPI clock-domain extraction.

Planned inputs:

```text
simv.daidir
DUT scope
optional SDC
```

Planned output:

```text
src_clock[]
dst_clock[]
clock_relation
clock_confidence
```

Possible relations:

```text
same_domain
cdc
multi_source
multi_destination
combinational
async_or_unknown
unknown
```

Do not assume Tcl Clock Analyzer APIs have identical Python bindings.

The installed Python NPI package must be inspected first.

---

## 23. Future Stage: Interface Group Inference

Higher-level interface inference may combine:

```text
RTL comment groups
signal naming patterns
connectivity
clock-domain consistency
```

Example:

```text
producer <-> consumer
CHANNEL_A
stream
```

may be transformed into a structured interface group after the base data is reliable.

This inference should remain separate from raw extraction.

---

## 24. Recommended Implementation Order

```text
1. Inspect parse_rtl_structure_v2.py
2. Inspect the installed pynpi package
3. Implement pynpi_runtime.py
4. Implement pynpi_probe.py
5. Validate against a real simv.daidir
6. Record the verified NPI APIs
7. Implement npi_design.py
8. Implement NPI port enumeration
9. Validate JSON output
10. Validate CSV output
11. Implement parameter effective/default/override handling
12. Merge RTL comments and source ranges
13. Add mismatch reporting
14. Add extract_dut_interface.py
15. Run pure-Python tests
16. Run real-NPI smoke tests
17. Only then implement connectivity
18. Add clock-domain analysis after connectivity
```

---

## 25. Design Principles

The implementation should follow these principles:

1. **Elaboration-first**  
   Structural facts come from the elaborated design database.

2. **Preserve source intent**  
   Do not lose parameter names or original range expressions.

3. **Do not guess NPI APIs**  
   Verify the locally installed Python package first.

4. **Do not invent unresolved information**  
   Use explicit `unknown` / unresolved states.

5. **Keep extraction separate from inference**  
   Raw ports, connectivity, clock domains, and interface inference should remain distinct layers.

6. **Load the design once**  
   Batch all queries within one NPI session.

7. **Keep CSV human-friendly and JSON machine-friendly**  
   JSON is the canonical structured output; CSV is an optional report format.