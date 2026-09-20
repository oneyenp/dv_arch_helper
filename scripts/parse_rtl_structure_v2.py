#!/usr/bin/env python3
"""Extract structural information from Verilog/SystemVerilog RTL.

Enhancements over the original parse_rtl_structure.py:
- Supports classic/non-ANSI port declarations in the module body, e.g.:
      // station <-> slice
      // PORT0
      // pkt
      input  [5:0] ctl0_slice_p_dlbo; // inline note
- Consecutive standalone // comments are merged into one port-group comment.
- A new standalone // comment block starts a new signal group.
- Inline // comments after a port declaration are stored on that signal row.
- Port table fields: port_type, width, range, sig_name, comment.
- Keeps the original JSON-oriented module/parameter/FSM/register/instantiation data.
- Optional CSV output for the port table.

Examples:
  python3 parse_rtl_structure_v2.py rtl/top.v
  python3 parse_rtl_structure_v2.py rtl/top.v --format csv --module my_dut
  python3 parse_rtl_structure_v2.py rtl/top.v --format csv --module my_dut -o dut_ports.csv
  python3 parse_rtl_structure_v2.py --dir rtl --format json
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path


PORT_COLUMNS = ["port_type", "width", "range", "sig_name", "comment"]


def read_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def strip_block_comments(text):
    """Remove /* ... */ comments but preserve // comments for port grouping."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def strip_comments(text):
    """Remove both // and /* ... */ comments for structural heuristics."""
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def split_line_comment(line):
    """Split a source line into code and // comment text."""
    if "//" not in line:
        return line, None
    code, comment = line.split("//", 1)
    return code, comment.strip()


def merge_comment_lines(lines):
    """Merge consecutive standalone // lines into one group comment."""
    parts = [x.strip() for x in lines if x.strip()]
    return " | ".join(parts)


def range_width(range_str):
    """Return numeric width for a simple packed range, else -1.

    Examples:
      ''        -> 1
      '[5:0]'   -> 6
      '[0:7]'   -> 8
      '[W-1:0]' -> -1
    """
    if not range_str:
        return 1

    # Only evaluate a single simple numeric packed dimension.
    m = re.fullmatch(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", range_str)
    if not m:
        return -1
    hi = int(m.group(1))
    lo = int(m.group(2))
    return abs(hi - lo) + 1


def _consume_prefix_qualifiers(rest):
    """Remove common Verilog/SV port qualifiers before the packed range/name."""
    qualifiers = {
        "wire", "reg", "logic", "bit", "tri", "tri0", "tri1",
        "wand", "wor", "uwire", "signed", "unsigned", "var",
        "supply0", "supply1",
    }

    while True:
        m = re.match(r"^\s*([A-Za-z_]\w*)\b", rest)
        if not m or m.group(1).lower() not in qualifiers:
            break
        rest = rest[m.end():]
    return rest


def parse_port_declaration(decl_text, inline_comment=""):
    """Parse one complete input/output/inout declaration ending in ';'.

    Returns one row per declared signal, allowing:
      input [7:0] a, b;
    """
    # Only use text before the first semicolon.
    core = decl_text.split(";", 1)[0].strip()
    m = re.match(r"^(input|output|inout)\b(.*)$", core, re.IGNORECASE | re.DOTALL)
    if not m:
        return []

    port_type = m.group(1).lower()
    rest = _consume_prefix_qualifiers(m.group(2))

    # Capture one or more packed ranges at the beginning, preserving spelling.
    ranges = []
    while True:
        rest = rest.lstrip()
        rm = re.match(r"^(\[[^\]]+\])", rest)
        if not rm:
            break
        ranges.append(rm.group(1).strip())
        rest = rest[rm.end():]
        rest = _consume_prefix_qualifiers(rest)

    range_str = "".join(ranges)
    width = range_width(range_str)

    rows = []
    # At this point rest should mostly be "name" or "name, name2".
    for item in rest.split(","):
        item = item.strip()
        if not item:
            continue

        # Remove default assignment if present; keep unpacked arrays out of sig_name.
        item = item.split("=", 1)[0].strip()
        nm = re.match(r"^([A-Za-z_]\w*)\b", item)
        if not nm:
            continue

        rows.append({
            "port_type": port_type,
            "width": width,
            "range": range_str,
            "sig_name": nm.group(1),
            "comment": inline_comment.strip(),
        })

    return rows


def extract_port_groups_from_module(module_text):
    """Extract classic/non-ANSI top-level port declarations with comment groups.

    Group semantics:
    - consecutive standalone // lines are merged;
    - that merged text becomes the group comment for subsequent ports;
    - the next standalone // block starts a new group;
    - inline // on a declaration is stored in that row's comment field.
    """
    groups = []
    current_group = None
    pending_comment_lines = []

    decl_buf = []
    decl_inline_comments = []
    in_decl = False
    in_subprogram = False

    def start_group_if_needed():
        nonlocal current_group, pending_comment_lines
        if pending_comment_lines:
            current_group = {
                "comment": merge_comment_lines(pending_comment_lines),
                "ports": [],
            }
            groups.append(current_group)
            pending_comment_lines = []
        elif current_group is None:
            current_group = {"comment": "", "ports": []}
            groups.append(current_group)

    def flush_decl():
        nonlocal decl_buf, decl_inline_comments, in_decl
        if not decl_buf:
            return
        start_group_if_needed()
        inline = " | ".join(x for x in decl_inline_comments if x)
        rows = parse_port_declaration(" ".join(decl_buf), inline)
        current_group["ports"].extend(rows)
        decl_buf = []
        decl_inline_comments = []
        in_decl = False

    for raw_line in module_text.splitlines():
        code, line_comment = split_line_comment(raw_line)
        stripped = code.strip()

        # Skip task/function argument declarations so they are not mistaken for module ports.
        if re.match(r"^(task|function)\b", stripped):
            in_subprogram = True
        if in_subprogram:
            if re.match(r"^(endtask|endfunction)\b", stripped):
                in_subprogram = False
            continue

        if in_decl:
            if stripped:
                decl_buf.append(stripped)
            if line_comment:
                decl_inline_comments.append(line_comment)
            if ";" in code:
                flush_decl()
            continue

        # Standalone // line: accumulate as a possible new group heading.
        if not stripped and line_comment is not None:
            pending_comment_lines.append(line_comment)
            continue

        # Blank line does not destroy the pending heading; it is still "above" the next port.
        if not stripped:
            continue

        if re.match(r"^(input|output|inout)\b", stripped, re.IGNORECASE):
            in_decl = True
            decl_buf = [stripped]
            decl_inline_comments = [line_comment] if line_comment else []
            if ";" in code:
                flush_decl()
            continue

        # A non-comment, non-port statement means an unattached comment block was not a port heading.
        # Keep an already-active group, but drop pending comments to avoid attaching unrelated text.
        pending_comment_lines = []

    if in_decl:
        flush_decl()

    # Remove empty groups that may have been created defensively.
    return [g for g in groups if g["ports"]]


def extract_ports_ansi(port_text):
    """Original-style ANSI module-header port extraction, used as fallback."""
    ports = []
    port_pattern = re.compile(
        r"(input|output|inout)\s+"
        r"(?:(logic|wire|reg)\s+)?"
        r"(?:(signed)\s+)?"
        r"(?:\[([^\]]+)\]\s*)?"
        r"(\w+)",
        re.IGNORECASE,
    )
    for p in port_pattern.finditer(port_text):
        direction = p.group(1).lower()
        width_expr = p.group(4)
        name = p.group(5)
        range_str = f"[{width_expr.strip()}]" if width_expr else ""
        ports.append({
            "port_type": direction,
            "width": range_width(range_str),
            "range": range_str,
            "sig_name": name,
            "comment": "",
        })
    return ports


def find_ansi_port_block(module_text):
    """Best-effort fallback compatible with the original parser."""
    clean = strip_comments(module_text)
    m = re.search(
        r"\bmodule\s+\w+\s*(?:#\s*\([^)]*\))?\s*\(([^;]*?)\)\s*;",
        clean,
        re.DOTALL,
    )
    return m.group(1) if m else None


def to_legacy_port(row):
    """Keep the original JSON port schema for existing downstream users."""
    width_expr = row["range"][1:-1] if row["range"].startswith("[") and row["range"].endswith("]") else row["range"]
    return {
        "name": row["sig_name"],
        "direction": row["port_type"],
        "width": row["width"],
        "width_expr": width_expr,
        "comment": row["comment"],
    }


def extract_modules(raw_text):
    """Extract module blocks and their port tables/groups."""
    text = strip_block_comments(raw_text)
    modules = []

    mod_pattern = re.compile(
        r"\bmodule\s+([A-Za-z_]\w*)\b(.*?)\bendmodule\b",
        re.DOTALL,
    )

    for m in mod_pattern.finditer(text):
        mod_name = m.group(1)
        module_text = m.group(0)

        # Prefer body declarations because they support the requested comment grouping.
        port_groups = extract_port_groups_from_module(module_text)

        # Fallback for ANSI-header style modules when no semicolon-style body ports were found.
        if not port_groups:
            port_block = find_ansi_port_block(module_text)
            ansi_ports = extract_ports_ansi(port_block) if port_block is not None else []
            if ansi_ports:
                port_groups = [{"comment": "", "ports": ansi_ports}]

        port_table = [p for g in port_groups for p in g["ports"]]
        legacy_ports = [to_legacy_port(p) for p in port_table]

        modules.append({
            "name": mod_name,
            "ports": legacy_ports,
            "port_groups": port_groups,
        })

    return modules


def extract_parameters(text):
    params = []
    param_pattern = re.compile(
        r"(parameter|localparam)\s+(?:(?:integer|real|logic|bit)\s+)?"
        r"(?:\[[^\]]+\]\s*)?"
        r"(\w+)\s*=\s*([^;,\n]+)",
        re.IGNORECASE,
    )
    for p in param_pattern.finditer(text):
        params.append({
            "kind": p.group(1).lower(),
            "name": p.group(2),
            "value": p.group(3).strip().rstrip(","),
        })
    return params


def extract_defines(text_with_comments):
    defines = []
    define_pattern = re.compile(r"`define\s+(\w+)\s+(.*?)$", re.MULTILINE)
    for d in define_pattern.finditer(text_with_comments):
        defines.append({"name": d.group(1), "value": d.group(2).strip()})
    return defines


def extract_fsm_candidates(text):
    candidates = []
    case_pattern = re.compile(r"case[zx]?\s*\((\w+)\)", re.IGNORECASE)
    for cm in case_pattern.finditer(text):
        state_var = cm.group(1)
        if state_var in [c["state_register"] for c in candidates]:
            continue
        start = cm.end()
        endcase_match = re.search(r"\bendcase\b", text[start:])
        if not endcase_match:
            continue
        case_body = text[start:start + endcase_match.start()]
        case_labels = re.findall(r"^\s*(\w+)\s*:", case_body, re.MULTILINE)
        states = [s for s in case_labels if s.lower() not in ("default", "begin", "end")]
        if len(states) >= 2:
            candidates.append({
                "state_register": state_var,
                "potential_states": states[:30],
                "state_count": len(states),
            })
    return candidates


def extract_registers(text):
    regs = []
    reg_pattern = re.compile(
        r"^\s*(?:reg|logic)\s+(?:\[[^\]]+\]\s*)?(\w+)\s*(?:\[[^\]]*\])?\s*[;=]",
        re.MULTILINE,
    )
    for r in reg_pattern.finditer(text):
        regs.append(r.group(1))
    return list(set(regs))


def extract_instantiations(text):
    insts = []
    inst_pattern = re.compile(
        r"^\s*(\w+)\s+(?:#\s*\([^)]*\)\s*)?(\w+)\s*\(",
        re.MULTILINE,
    )
    keywords = {
        "module", "endmodule", "function", "endfunction", "task", "endtask",
        "always", "initial", "assign", "if", "else", "for", "while",
        "case", "casez", "casex", "begin", "end", "generate",
        "input", "output", "inout", "wire", "reg", "logic", "integer",
        "parameter", "localparam", "typedef", "enum", "struct",
    }
    for m in inst_pattern.finditer(text):
        mod_type = m.group(1)
        inst_name = m.group(2)
        if mod_type.lower() not in keywords and inst_name.lower() not in keywords:
            insts.append({"module_type": mod_type, "instance_name": inst_name})
    return insts


def parse_file(filepath):
    raw_text = read_file(filepath)
    clean_text = strip_comments(raw_text)
    return {
        "file": filepath,
        "modules": extract_modules(raw_text),
        "parameters": extract_parameters(clean_text),
        "defines": extract_defines(raw_text),
        "fsm_candidates": extract_fsm_candidates(clean_text),
        "registers": extract_registers(clean_text),
        "instantiations": extract_instantiations(clean_text),
    }


def collect_input_files(args):
    if args.directory:
        rtl_dir = Path(args.directory)
        if not rtl_dir.is_dir():
            raise FileNotFoundError(f"RTL directory not found: {rtl_dir}")
        return [str(p) for p in sorted(rtl_dir.iterdir()) if p.suffix.lower() in (".sv", ".v", ".svh", ".vh")]
    return args.files


def iter_selected_modules(results, module_name=None):
    for result in results:
        for module in result["modules"]:
            if module_name and module["name"] != module_name:
                continue
            yield result["file"], module


def write_csv(results, fp, module_name=None):
    """Write grouped port table.

    CSV convention:
      - fixed columns: port_type,width,range,sig_name,comment
      - a group heading is emitted as a comment-only row
      - groups are kept contiguous; no blank rows are emitted
      - inline comments remain on the signal row
    """
    writer = csv.DictWriter(fp, fieldnames=PORT_COLUMNS, lineterminator="\n")
    writer.writeheader()

    selected = list(iter_selected_modules(results, module_name))
    multi_module = len(selected) > 1

    for mod_idx, (file_path, module) in enumerate(selected):
        if multi_module:
            writer.writerow({"comment": f"MODULE: {module['name']} ({file_path})"})

        for group_idx, group in enumerate(module["port_groups"]):
            if group["comment"]:
                writer.writerow({"comment": group["comment"]})
            for row in group["ports"]:
                writer.writerow(row)


def build_arg_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*", help="RTL files (.v/.sv/.svh/.vh)")
    p.add_argument("--dir", dest="directory", help="Scan one RTL directory (non-recursive, same behavior as original)")
    p.add_argument("--format", choices=("json", "csv"), default="json", help="Output format (default: json)")
    p.add_argument("--module", help="Only emit this module in CSV mode")
    p.add_argument("-o", "--output", help="Output file; default stdout")
    return p


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if bool(args.directory) == bool(args.files):
        parser.error("Specify either RTL file(s) or --dir <rtl_directory>")

    files = collect_input_files(args)
    results = []
    for f in files:
        if not os.path.isfile(f):
            print(f"Warning: {f} not found, skipping", file=sys.stderr)
            continue
        results.append(parse_file(f))

    out_fp = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        if args.format == "json":
            json.dump(results, out_fp, indent=2, ensure_ascii=False)
            out_fp.write("\n")
        else:
            write_csv(results, out_fp, args.module)
    finally:
        if args.output:
            out_fp.close()


if __name__ == "__main__":
    main()