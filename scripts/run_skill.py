#!/usr/bin/env python3
"""Deterministic scientific-PDF structure reader (standard library only).

Reads /input/case.json (or --case), locates the actual PDF it references,
extracts page-anchored text blocks with a reading-order heuristic, detects
headings / captions / formula numbers / references, then writes
/app/output/result.json while preserving case_id and every original
output_contract field. No network access, no external packages.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import zlib

DEFAULT_CASE = "/input/case.json"
DEFAULT_OUT = "/app/output/result.json"
DEFAULT_WORK = "/app/work"

WS = " \t\r\n"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, payload):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def contract_names(case):
    """Return the top-level field names declared by the original contract."""
    oc = case.get("output_contract")
    names = []
    if isinstance(oc, dict):
        props = oc.get("properties")
        if isinstance(props, dict) and props:
            names = list(props.keys())
        elif isinstance(oc.get("fields"), (list, dict)):
            fields = oc["fields"]
            names = list(fields.keys()) if isinstance(fields, dict) else [
                f if isinstance(f, str) else f.get("name") for f in fields
            ]
        elif isinstance(oc.get("required"), list):
            names = list(oc["required"])
        else:
            skip = {"type", "properties", "required", "additionalProperties",
                    "$schema", "description", "title", "$defs", "definitions"}
            names = [k for k in oc.keys() if k not in skip]
    elif isinstance(oc, list):
        names = [n if isinstance(n, str) else (n or {}).get("name") for n in oc]
    seen, out = set(), []
    for n in names:
        if isinstance(n, str) and n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def fill_contract(case, values):
    """Guarantee every original contract field survives, with honest values."""
    notes = {}
    out = {}
    for name in contract_names(case):
        if name in values:
            out[name] = values[name]
        else:
            out[name] = None
            notes[name] = "field declared by output_contract but not mapped by this skill; kept as null"
    if not out:
        notes["_no_contract"] = "input case declared no recognizable output_contract; business fields only"
    return out, notes


def find_pdf_paths(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.lower().endswith(".pdf"):
                acc.append(v)
            else:
                find_pdf_paths(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            find_pdf_paths(v, acc)
    elif isinstance(obj, str) and obj.lower().endswith(".pdf"):
        acc.append(obj)


def resolve_path(raw, case_path):
    if os.path.isabs(raw):
        return raw
    for base in (os.path.dirname(os.path.abspath(case_path)), "/input", "/app", os.getcwd()):
        cand = os.path.normpath(os.path.join(base, raw))
        if os.path.exists(cand):
            return cand
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(case_path)), raw))


# ---------------------------------------------------------------- PDF parsing

def _unescape_literal(raw):
    out, i, n = bytearray(), 0, len(raw)
    while i < n:
        c = raw[i]
        if c == 0x5C and i + 1 < n:  # backslash
            nxt = raw[i + 1]
            mapping = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12,
                       0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
            if nxt in mapping:
                out.append(mapping[nxt]); i += 2; continue
            if 0x30 <= nxt <= 0x37:
                j, digits = i + 1, b""
                while j < n and len(digits) < 3 and 0x30 <= raw[j] <= 0x37:
                    digits += raw[j:j + 1]; j += 1
                out.append(int(digits, 8) & 0xFF); i = j; continue
            if nxt in (0x0A, 0x0D):
                i += 2
                if nxt == 0x0D and i < n and raw[i] == 0x0A:
                    i += 1
                continue
            out.append(nxt); i += 2; continue
        out.append(c); i += 1
    return bytes(out)


class Tokenizer:
    """Minimal PDF content-stream tokenizer: numbers, names, strings, arrays."""

    def __init__(self, data):
        self.data = data
        self.i = 0
        self.n = len(data)

    def tokens(self):
        d, n = self.data, self.n
        while self.i < n:
            c = d[self.i]
            if c in b" \t\r\n\f\x00":
                self.i += 1; continue
            if c == 0x25:  # %
                while self.i < n and d[self.i] not in b"\r\n":
                    self.i += 1
                continue
            if c == 0x28:  # (
                depth, start = 1, self.i + 1
                self.i += 1
                while self.i < n and depth:
                    ch = d[self.i]
                    if ch == 0x5C:
                        self.i += 2; continue
                    if ch == 0x28:
                        depth += 1
                    elif ch == 0x29:
                        depth -= 1
                        if depth == 0:
                            break
                    self.i += 1
                raw = d[start:self.i]
                self.i += 1
                yield ("str", _unescape_literal(raw))
                continue
            if c == 0x3C and self.i + 1 < n and d[self.i + 1] != 0x3C:  # <hex>
                end = d.find(b">", self.i)
                if end < 0:
                    end = n
                hexs = re.sub(rb"[^0-9A-Fa-f]", b"", d[self.i + 1:end])
                if len(hexs) % 2:
                    hexs += b"0"
                self.i = end + 1
                yield ("str", bytes.fromhex(hexs.decode("ascii")))
                continue
            if c == 0x2F:  # /Name
                j = self.i + 1
                while j < n and d[j] not in b" \t\r\n\f/[]()<>":
                    j += 1
                yield ("name", d[self.i + 1:j].decode("latin-1"))
                self.i = j; continue
            if c == 0x5B:
                self.i += 1
                yield ("[", None); continue
            if c == 0x5D:
                self.i += 1
                yield ("]", None); continue
            m = re.match(rb"[-+]?(\d+\.?\d*|\.\d+)", d[self.i:self.i + 32])
            if m:
                self.i += m.end()
                try:
                    yield ("num", float(m.group(0)))
                except ValueError:
                    yield ("num", 0.0)
                continue
            if c == 0x27 or c == 0x22:
                self.i += 1
                yield ("op", chr(c)); continue
            j = self.i
            while j < n and d[j] not in b" \t\r\n\f[]()<>/%":
                j += 1
            if j == self.i:
                j += 1
            yield ("op", d[self.i:j].decode("latin-1"))
            self.i = j


def _stream_of(body):
    idx = body.find(b"stream")
    if idx < 0:
        return None, body
    dict_part = body[:idx]
    start = idx + 6
    if body[start:start + 2] == b"\r\n":
        start += 2
    elif body[start:start + 1] in (b"\n", b"\r"):
        start += 1
    end = body.find(b"endstream", start)
    if end < 0:
        end = len(body)
    return body[start:end], dict_part


def extract_page_text(data, page_body):
    contents = []
    m = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", page_body)
    if m:
        contents = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", m.group(1))]
    if not contents:
        inline, _ = _stream_of(page_body)
        if inline:
            contents = [None]
    chunks = []
    if contents == [None]:
        raw, _ = _stream_of(page_body)
        chunks.append(raw or b"")
    else:
        for num in contents:
            om = re.search(rb"(?<![0-9])" + str(num).encode() + rb"\s+\d+\s+obj(.*?)endobj",
                           data, re.S)
            if not om:
                continue
            raw, dpart = _stream_of(om.group(1))
            if raw is None:
                continue
            if b"/FlateDecode" in dpart:
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    continue
            chunks.append(raw)
    runs = []
    for chunk in chunks:
        if not chunk:
            continue
        runs.extend(_runs_from_content(chunk))
    return runs


def _runs_from_content(content):
    tk = Tokenizer(content)
    stack, runs = [], []
    x = y = 0.0
    leading = 0.0
    size = 10.0
    for kind, val in tk.tokens():
        if kind != "op":
            stack.append((kind, val))
            continue
        op = val
        try:
            if op == "BT":
                x = y = 0.0
            elif op == "Tm" and len(stack) >= 6:
                nums = [s[1] for s in stack[-6:] if s[0] == "num"]
                if len(nums) == 6:
                    x, y = nums[4], nums[5]
            elif op in ("Td", "TD") and len(stack) >= 2:
                nums = [s[1] for s in stack[-2:] if s[0] == "num"]
                if len(nums) == 2:
                    x += nums[0]; y += nums[1]
                    if op == "TD":
                        leading = -nums[1]
            elif op == "T*":
                y -= leading or size * 1.2
            elif op == "TL" and stack and stack[-1][0] == "num":
                leading = stack[-1][1]
            elif op == "Tf" and stack:
                nums = [s[1] for s in stack if s[0] == "num"]
                if nums:
                    size = abs(nums[-1]) or size
            elif op in ("Tj", "'", '"'):
                if op in ("'", '"'):
                    y -= leading or size * 1.2
                if stack and stack[-1][0] == "str":
                    txt = stack[-1][1].decode("latin-1", "replace")
                    runs.append({"x": x, "y": y, "size": size, "text": txt})
            elif op == "TJ":
                parts, inside = [], False
                for k, v in reversed(stack):
                    if k == "]" and not inside:
                        inside = True
                        continue
                    if k == "[":
                        break
                    if inside and k == "str":
                        parts.append(v)
                if parts:
                    text_part = "".join(p.decode("latin-1", "replace") for p in reversed(parts))
                    runs.append({"x": x, "y": y, "size": size, "text": text_part})
        except Exception:
            pass
        stack = []
    return runs


def _media_box(page_body):
    m = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", page_body)
    if m:
        nums = [abs(float(v)) for v in m.groups()]
        return nums[2] or 612.0, nums[3] or 792.0
    return 612.0, 792.0


def _lines_from_runs(runs):
    if not runs:
        return []
    items = sorted(runs, key=lambda r: (-r["y"], r["x"]))
    lines = []
    for r in items:
        if not r["text"].strip():
            continue
        placed = False
        for line in lines:
            tol = max(1.5, 0.5 * min(line["size"], r["size"]))
            near_y = abs(line["y"] - r["y"]) <= tol
            x0, x1 = line["x0"], line["x1"]
            near_x = x0 - 3.0 * max(1.0, line["size"]) <= r["x"] <= \
                x1 + 3.0 * max(1.0, line["size"])
            if near_y and near_x:
                line["runs"].append(r)
                line["size"] = max(line["size"], r["size"])
                line["x0"] = min(line["x0"], r["x"])
                line["x1"] = max(line["x1"], r["x"] + len(r["text"]) * 0.5 * r["size"])
                placed = True
                break
        if not placed:
            lines.append({"y": r["y"], "size": r["size"], "runs": [r],
                          "x0": r["x"], "x1": r["x"] + len(r["text"]) * 0.5 * r["size"]})
    out = []
    for line in lines:
        parts, last_end = [], None
        for r in sorted(line["runs"], key=lambda r: r["x"]):
            if last_end is not None and r["x"] - last_end > 0.16 * max(1.0, line["size"]):
                parts.append(" ")
            parts.append(r["text"])
            last_end = r["x"] + len(r["text"]) * 0.5 * max(1.0, line["size"])
        text = "".join(parts).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            out.append({"y": line["y"], "size": line["size"], "text": text,
                        "x0": round(line["x0"], 2),
                        "x1": round(max(line["x1"],
                                       max(r["x"] for r in line["runs"])), 2)})
    return out


HEADING_NUM = re.compile(r"^(\d+(?:\.\d+){0,4})[.)]?\s+\S")
NAMED_HEADING = re.compile(
    r"^(abstract|introduction|background|related work|methods?|materials and methods|"
    r"results?|discussion|conclusions?|references|bibliography|acknowledg(e)?ments?|"
    r"appendix|supplementary)\b", re.I)
CAPTION = re.compile(r"^(fig(?:ure)?\.?\s*\d+|table\s+(?:s?\d+|[IVX]+))\b", re.I)
FORMULA_NO = re.compile(r"\((\d+(?:[a-z])?)\)\s*$")


def _classify(text, size, median_size, in_references):
    if in_references:
        return "reference"
    if CAPTION.match(text):
        return "caption"
    if FORMULA_NO.search(text) and re.search(r"[=+\-−×÷∑∫^_/]", text):
        return "formula"
    if len(text) <= 140 and (HEADING_NUM.match(text) or NAMED_HEADING.match(text)):
        return "heading"
    if size < median_size * 0.88 and len(text) <= 200:
        return "footnote"
    return "body"


def _detect_two_column(lines, width):
    if len(lines) < 6:
        return False
    left = sum(1 for ln in lines if ln["x0"] < width * 0.5)
    right = sum(1 for ln in lines if ln["x0"] >= width * 0.5)
    return left >= 3 and right >= 3


def _order_lines(lines, width):
    two_col = _detect_two_column(lines, width)
    if not two_col:
        return sorted(lines, key=lambda ln: (-ln["y"], ln["x0"])), False
    spanning = [ln for ln in lines if ln["x1"] - ln["x0"] > width * 0.68]
    span_ids = {id(ln) for ln in spanning}
    left = [ln for ln in lines if id(ln) not in span_ids and ln["x0"] < width * 0.5]
    right = [ln for ln in lines if id(ln) not in span_ids and ln["x0"] >= width * 0.5]
    ordered = (sorted(spanning, key=lambda ln: -ln["y"]) +
               sorted(left, key=lambda ln: (-ln["y"], ln["x0"])) +
               sorted(right, key=lambda ln: (-ln["y"], ln["x0"])))
    return ordered, True


def parse_pdf(path, raw):
    pages = []
    page_objs = []
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", raw, re.S):
        body = m.group(3)
        if re.search(rb"/Type\s*/Page\b", body):
            page_objs.append((int(m.group(1)), body))
    if not page_objs:
        for m in re.finditer(rb"/Type\s*/Page\b", raw):
            start = raw.rfind(b"obj", 0, m.start())
            end = raw.find(b"endobj", m.start())
            if start > 0 and end > 0:
                page_objs.append((len(page_objs) + 1, raw[start:end]))
    for idx, (_, body) in enumerate(page_objs, 1):
        width, height = _media_box(body)
        try:
            runs = extract_page_text(raw, body)
        except Exception as exc:  # keep other pages alive
            pages.append({"page": idx, "width": width, "height": height,
                          "blocks": [], "text": "", "error": type(exc).__name__})
            continue
        lines = _lines_from_runs(runs)
        median_size = sorted(ln["size"] for ln in lines)[len(lines) // 2] if lines else 10.0
        ordered, two_col = _order_lines(lines, width)
        blocks, current, last_y, in_refs = [], None, None, False
        for ln in ordered:
            if re.match(r"^(references|bibliography)\b", ln["text"], re.I):
                in_refs = True
            kind = _classify(ln["text"], ln["size"], median_size, in_refs)
            gap = (last_y - ln["y"]) if last_y is not None else 0
            same_block = (current is not None and gap <= max(1.35 * median_size, 11)
                          and abs(gap) <= height * 0.6 and current["kind"] == kind)
            if not same_block:
                current = {"lines": [ln], "size": ln["size"], "kind": kind,
                           "in_refs": in_refs}
                blocks.append(current)
            else:
                current["lines"].append(ln)
            last_y = ln["y"]
        page_blocks = []
        for b_idx, blk in enumerate(blocks, 1):
            text = "\n".join(ln["text"] for ln in blk["lines"])
            page_blocks.append({
                "block_id": "p%02d-b%02d" % (idx, b_idx),
                "page": idx,
                "bbox": [round(min(ln["x0"] for ln in blk["lines"]), 2),
                         round(min(ln["y"] for ln in blk["lines"]), 2),
                         round(max(ln["x1"] for ln in blk["lines"]), 2),
                         round(max(ln["y"] for ln in blk["lines"]), 2)],
                "text": text,
                "sha256": sha256_bytes(text.encode("utf-8")),
                "kind": blk["kind"],
                "size": round(blk["size"], 2),
                "line_count": len(blk["lines"]),
            })
        pages.append({"page": idx, "width": width, "height": height,
                      "blocks": page_blocks, "two_column": two_col,
                      "text": "\n".join(pb["text"] for pb in page_blocks)})
    return pages


def structure_pages(pages):
    sections, captions, formulas, footnotes = [], [], [], []
    in_references = False
    heading_stack = []
    all_sizes = [b["size"] for p in pages for b in p["blocks"]]
    median_size = sorted(all_sizes)[len(all_sizes) // 2] if all_sizes else 10.0
    for page in pages:
        for blk in page["blocks"]:
            text = blk["text"]
            if re.match(r"^(references|bibliography)\b", text, re.I):
                in_references = True
            kind = blk.get("kind")
            if kind not in ("heading", "caption", "formula", "footnote", "reference"):
                kind = _classify(text, blk.get("size", 10.0), median_size, in_references)
            blk["kind"] = kind
            if kind == "heading":
                if re.match(r"^(references|bibliography)\b", text, re.I):
                    in_references = True
                m = HEADING_NUM.match(text)
                level = len(m.group(1).split(".")) if m else 1
                while heading_stack and heading_stack[-1]["level"] >= level:
                    heading_stack.pop()
                parent = heading_stack[-1]["section_id"] if heading_stack else None
                sid = "S%02d" % (len(sections) + 1)
                entry = {"section_id": sid, "title": text, "level": level,
                         "parent_id": parent, "page": blk["page"],
                         "block_id": blk["block_id"]}
                sections.append(entry)
                heading_stack.append(entry)
            elif kind == "caption":
                kind2 = "table_caption" if re.match(r"^table", text, re.I) else "figure_caption"
                captions.append({"caption_id": "C%02d" % (len(captions) + 1),
                                 "kind": kind2, "text": text, "page": blk["page"],
                                 "block_id": blk["block_id"]})
            elif kind == "formula":
                formulas.append({"formula_label": FORMULA_NO.search(text).group(1),
                                 "text": text, "page": blk["page"],
                                 "block_id": blk["block_id"]})
            elif kind == "footnote":
                footnotes.append({"text": text, "page": blk["page"],
                                  "block_id": blk["block_id"]})
    return sections, captions, formulas, footnotes


def pages_from_structured(obj):
    raw_pages = obj.get("pages")
    if isinstance(raw_pages, list) and raw_pages:
        pages = []
        for i, p in enumerate(raw_pages, 1):
            if isinstance(p, str):
                blocks = [{"text": p}]
            elif isinstance(p, dict):
                blocks = p.get("blocks") or [{"text": p.get("text", "")}]
            else:
                blocks = []
            pb = []
            for j, b in enumerate(blocks, 1):
                text = b if isinstance(b, str) else str(b.get("text", ""))
                pb.append({"block_id": "p%02d-b%02d" % (i, j), "page": i,
                           "bbox": None, "text": text,
                           "sha256": sha256_bytes(text.encode("utf-8")),
                           "kind": "body", "size": 10.0, "line_count": 1})
            pages.append({"page": i, "width": None, "height": None, "blocks": pb,
                          "two_column": False,
                          "text": "\n".join(x["text"] for x in pb)})
        return pages
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read a scientific PDF into page-anchored structure.")
    ap.add_argument("--case", default=DEFAULT_CASE)
    ap.add_argument("--out", "--output", default=DEFAULT_OUT)
    ap.add_argument("--work", default=DEFAULT_WORK)
    args = ap.parse_args(argv)

    case_path = args.case
    try:
        os.makedirs(args.work, exist_ok=True)
    except OSError:
        pass

    case = {}
    case_id = None
    try:
        with open(case_path, "r", encoding="utf-8") as fh:
            case = json.load(fh)
        case_id = case.get("case_id")
    except FileNotFoundError:
        payload = {"case_id": None, "status": "insufficient_input",
                   "errors": [{"code": "case_not_found", "message": "case file not found",
                               "path": case_path}],
                   "result": {"pages": [], "sections": []}, "sources": [],
                   "uncertainty": ["no input case was readable"], "limitations": [],
                   "stats": {}, "contract_notes": {}}
        write_json(args.out, payload)
        print(json.dumps({"status": payload["status"], "error": "case_not_found"}))
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        payload = {"case_id": None, "status": "insufficient_input",
                   "errors": [{"code": "case_unreadable", "message": str(exc)}],
                   "result": {"pages": [], "sections": []}, "sources": [],
                   "uncertainty": [], "limitations": [], "stats": {},
                   "contract_notes": {}}
        write_json(args.out, payload)
        print(json.dumps({"status": "insufficient_input", "error": "case_unreadable"}))
        return 2

    try:
        pdf_candidates = []
        find_pdf_paths(case, pdf_candidates)
        seen, pdf_paths = set(), []
        for cand in pdf_candidates:
            resolved = resolve_path(cand, case_path)
            if resolved not in seen:
                seen.add(resolved); pdf_paths.append(resolved)

        pages, sources, errors, uncertainty = [], [], [], []
        limitations = []
        for path in pdf_paths:
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
            except OSError as exc:
                errors.append({"code": "pdf_unreadable", "path": path, "message": str(exc)})
                uncertainty.append("PDF not readable: " + os.path.basename(path))
                continue
            sources.append({"path": os.path.basename(path), "bytes": len(raw),
                            "sha256": sha256_bytes(raw)})
            try:
                parsed = parse_pdf(path, raw)
            except Exception as exc:
                errors.append({"code": "pdf_parse_failed", "path": path,
                               "message": type(exc).__name__ + ": " + str(exc)})
                parsed = []
            offset = len(pages)
            for p in parsed:
                p["page"] = p["page"] + offset
                for b in p["blocks"]:
                    b["block_id"] = "d%02d-" % (offset + 1) + b["block_id"]
                    b["page"] = p["page"]
                pages.append(p)
            if not parsed:
                uncertainty.append("no page objects parsed from " + os.path.basename(path))

        if not pages:
            structured = pages_from_structured(case)
            if structured:
                pages = structured
                sources.append({"path": "case.json#structured_pages",
                                "bytes": None, "sha256": None})
                limitations.append("no PDF found; used structured page text supplied in case")
            else:
                uncertainty.append("no PDF and no structured page text found in case")

        sections, captions, formulas, footnotes = structure_pages(pages)
        empty_pages = [p["page"] for p in pages if not p["blocks"]]
        if empty_pages:
            uncertainty.append("pages without extractable text: " + str(empty_pages) +
                               " (may need OCR)")
        if pages and any(p.get("two_column") for p in pages):
            limitations.append("two-column reading order is heuristic (coordinate clustering)")
        limitations.append("glyphs decoded as latin-1 bytes when no ToUnicode map is applied; "
                           "CJK or subset fonts may be garbled")

        status = "success"
        if errors or empty_pages or not pages:
            status = "partial" if pages else "insufficient_input"
        values = {
            "status": status,
            "pages": pages,
            "sections": sections,
            "captions": captions,
            "formula_numbers": formulas,
            "footnotes": footnotes,
            "result": {"pages": pages, "sections": sections, "captions": captions,
                       "formula_numbers": formulas, "footnotes": footnotes},
            "sources": sources,
            "uncertainty": uncertainty,
            "limitations": limitations,
            "stats": {"page_count": len(pages),
                      "block_count": sum(len(p["blocks"]) for p in pages),
                      "char_count": sum(len(p["text"]) for p in pages),
                      "two_column_pages": sum(1 for p in pages if p.get("two_column")),
                      "empty_pages": len(empty_pages)},
            "errors": errors,
        }
        payload, notes = fill_contract(case, values)
        payload["case_id"] = case_id
        payload["status"] = status
        for key in ("result", "sources", "uncertainty", "limitations", "stats", "errors"):
            payload.setdefault(key, values.get(key))
        payload["contract_notes"] = notes
        write_json(args.out, payload)
        print(json.dumps({"status": status, "case_id": case_id,
                          "pages": len(pages), "blocks": values["stats"]["block_count"]},
                         ensure_ascii=False))
        return 0
    except Exception as exc:
        values = {"status": "failed",
                  "result": {"pages": [], "sections": []},
                  "errors": [{"code": "unhandled_error",
                              "message": type(exc).__name__ + ": " + str(exc)}],
                  "sources": [], "uncertainty": [], "limitations": [],
                  "stats": {}, "contract_notes": {}}
        try:
            payload, notes = fill_contract(case, values)
            payload["case_id"] = case_id
            payload["contract_notes"] = notes
            write_json(args.out, payload)
        except Exception:
            pass
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.path.join("/app/output", "result.json")
            os.makedirs("/app/output", exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    if not os.path.isfile("/app/output/result.json"):
        try:
            os.makedirs("/app/output", exist_ok=True)
            with open("/app/output/result.json", "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0)
