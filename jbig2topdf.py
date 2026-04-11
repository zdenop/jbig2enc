#!/usr/bin/env python3
# Copyright 2006 Google Inc.
# Author: agl@imperialviolet.org (Adam Langley)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""JBIG2 to PDF converter.

Converts output from the JBIG2 encoder (https://github.com/agl/jbig2enc)
into a valid PDF document.

Usage:
    ./jbig2 -s -p <options> image1.jpeg image2.jpeg ...
    python jbig2topdf.py output > out.pdf
"""

from __future__ import annotations

import glob

import sys

from dataclasses import dataclass, field

from typing import ClassVar

import struct

DEFAULT_DPI = 72
PAGE_HEADER_SEGMENT_OFFSET = slice(11, 27)
PAGE_HEADER_FORMAT = ">IIII"  # width, height, xres, yres (big-endian unsigned ints)

from pathlib import Path

# ---------------------------------------------------------------------------
# PDF primitives
# ---------------------------------------------------------------------------


def _pdf_ref(obj_id: int) -> str:
    """Returns an indirect object reference string."""
    return f"{obj_id} 0 R"


def _pdf_dict(values: dict[str, str]) -> str:
    """Serialises a Python dict to a PDF dictionary literal."""
    entries = " ".join(f"/{k} {v}" for k, v in values.items())
    return f"<< {entries} >>\n"


@dataclass
class PdfObj:
    """A single PDF indirect object."""

    _id_counter: ClassVar[int] = 1

    d: dict[str, str] = field(default_factory=dict)
    stream: bytes | None = None
    obj_id: int = field(init=False)

    def __post_init__(self) -> None:
        self.obj_id = PdfObj._id_counter
        PdfObj._id_counter += 1
        if self.stream is not None:
            self.d["Length"] = str(len(self.stream))

    @property
    def ref(self) -> str:
        return _pdf_ref(self.obj_id)

    def serialise(self) -> bytes:
        """Returns the object serialised as raw bytes."""
        parts: list[bytes] = [_pdf_dict(self.d).encode("latin-1")]
        if self.stream is not None:
            parts += [b"stream\n", self.stream, b"\nendstream\n"]
        parts.append(b"endobj\n")
        return b"".join(parts)


# ---------------------------------------------------------------------------
# PDF document
# ---------------------------------------------------------------------------


class PdfDoc:
    """Builds a minimal, spec-compliant PDF document."""

    def __init__(self) -> None:
        self._objects: list[PdfObj] = []
        self._pages: list[PdfObj] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(self, obj: PdfObj) -> PdfObj:
        self._objects.append(obj)
        return obj

    def _new(self, d: dict[str, str] | None = None, stream: bytes | None = None) -> PdfObj:
        return self._add(PdfObj(d=d or {}, stream=stream))

    # ------------------------------------------------------------------
    # Page construction
    # ------------------------------------------------------------------

    def add_page(
        self,
        image_data: bytes,
        width: int,
        height: int,
        xres: int,
        yres: int,
        globals_ref: str | None,
        pages_id: int,
    ) -> PdfObj:
        """Creates and registers all objects needed for one page."""
        pt_w = width * 72 / xres
        pt_h = height * 72 / yres

        # Image XObject
        xobj_d: dict[str, str] = {
            "Type": "/XObject",
            "Subtype": "/Image",
            "Width": str(width),
            "Height": str(height),
            "ColorSpace": "/DeviceGray",
            "BitsPerComponent": "1",
            "Filter": "/JBIG2Decode",
        }
        if globals_ref:
            xobj_d["DecodeParms"] = f"<< /JBIG2Globals {globals_ref} >>"
        xobj = self._new(xobj_d, image_data)

        # Content stream: scale image to page size
        content_stream = (
            f"q {pt_w:.6f} 0 0 {pt_h:.6f} 0 0 cm /Im1 Do Q".encode("latin-1")
        )
        contents_obj = self._new({}, content_stream)

        # Resource dictionary
        resources_obj = self._new(
            {
                "ProcSet": "[/PDF /ImageB]",
                "XObject": f"<< /Im1 {xobj.ref} >>",
            }
        )

        # Page object
        page_obj = self._new(
            {
                "Type": "/Page",
                "Parent": _pdf_ref(pages_id),
                "MediaBox": f"[ 0 0 {pt_w:.6f} {pt_h:.6f} ]",
                "Contents": contents_obj.ref,
                "Resources": resources_obj.ref,
            }
        )
        self._pages.append(page_obj)
        return page_obj

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialises the complete PDF document to bytes."""
        buf: list[bytes] = []
        offsets: list[int] = []
        pos = 0

        def write(data: bytes) -> None:
            nonlocal pos
            buf.append(data)
            pos += len(data)

        write(b"%PDF-1.4\n")

        for obj in self._objects:
            offsets.append(pos)
            header = f"{obj.obj_id} 0 obj\n".encode("latin-1")
            write(header)
            write(obj.serialise())
            write(b"\n")

        xref_pos = pos
        n = len(offsets) + 1
        xref_lines = [f"xref\n0 {n}\n0000000000 65535 f \n"]
        xref_lines += [f"{off:010d} 00000 n \n" for off in offsets]
        write("".join(xref_lines).encode("latin-1"))

        trailer = (
            f"trailer\n<< /Size {n}\n/Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        )
        write(trailer.encode("latin-1"))

        return b"".join(buf)


# ---------------------------------------------------------------------------
# Core conversion logic
# ---------------------------------------------------------------------------

def _read_bytes(path: Path, label: str) -> bytes | None:
    """Reads a file and returns its bytes, or logs an error and returns None."""
    try:
        return path.read_bytes()
    except OSError as exc:
        sys.stderr.write(f"Error reading {label} '{path}': {exc}\n")
        return None

def _parse_page_header(data: bytes, path: Path) -> tuple[int, int, int, int] | None:
    """Extracts (width, height, xres, yres) from a JBIG2 page segment header."""
    try:
        return struct.unpack(PAGE_HEADER_FORMAT, data[PAGE_HEADER_SEGMENT_OFFSET])
    except struct.error as exc:
        sys.stderr.write(f"Error parsing JBIG2 header in '{path}': {exc}\n")
        return None

def create_pdf(symbol_table: str = "symboltable", page_files: list[str] | None = None) -> None:
    """Builds a PDF from a JBIG2 symbol table and page files, writing to stdout."""
    page_paths = sorted(Path(p) for p in (page_files or glob.glob("page-*")))

    # Reset the global object ID counter for repeatable/testable output.
    PdfObj._id_counter = 1
    doc = PdfDoc()

    # Fixed-layout objects: catalog (id=1), outlines (id=2), pages (id=3).
    catalog = doc._new({"Type": "/Catalog", "Outlines": _pdf_ref(2), "Pages": _pdf_ref(3)})
    outlines = doc._new({"Type": "/Outlines", "Count": "0"})  # noqa: F841
    pages_obj = doc._new({"Type": "/Pages"})

    assert catalog.obj_id == 1, "Catalog must be object 1"
    assert pages_obj.obj_id == 3, "Pages must be object 3"

    # Optional global symbol table
    globals_ref: str | None = None
    if symbol_table:
        sym_path = Path(symbol_table)
        sym_data = _read_bytes(sym_path, "symbol table")
        if sym_data is None:
            return
        symd = doc._new({}, sym_data)
        globals_ref = symd.ref

    # Process each page
    page_objs: list[PdfObj] = []
    for path in page_paths:
        data = _read_bytes(path, "page file")
        if data is None: continue

        header = _parse_page_header(data, path)
        if header is None: continue

        width, height, xres, yres = header
        xres = xres or DEFAULT_DPI
        yres = yres or DEFAULT_DPI

        page = doc.add_page(data, width, height, xres, yres, globals_ref, pages_obj.obj_id)
        page_objs.append(page)

    # Update /Pages Kids and Count now that all pages are known
    pages_obj.d["Count"] = str(len(page_objs))
    pages_obj.d["Kids"] = "[" + " ".join(p.ref for p in page_objs) + "]"

    sys.stdout.buffer.write(doc.to_bytes())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _usage(script: str, msg: str = "") -> None:
    if msg:
        sys.stderr.write(f"{script}: {msg}\n")
    sys.stderr.write(
        f"""
Usage:
  {script} [basename] > out.pdf
  {script} -s [page.jb2]... > out.pdf

  Read symbol table from `basename.sym` and pages from `basename.[0-9]*`.
  If basename is omitted: symbol table from `symboltable`, pages from `page-*`.

  -s  Standalone mode — no global symbol table.
"""
    )
    sys.exit(1)


def _parse_args(argv: list[str]) -> tuple[str, list[str]]:
    """Returns (symbol_table_path, page_file_list)."""
    script = argv[0]
    args = argv[1:]

    if "-s" in args:
        pages = [a for a in args if a != "-s"]
        return "", pages

    match len(args):
        case 0:
            sym = "symboltable"
            pages = glob.glob("page-*")
        case 1:
            base = args[0]
            sym = f"{base}.sym"
            pages = glob.glob(f"{base}.[0-9]*")
        case _:
            _usage(script, "wrong number of arguments!")

    if not Path(sym).exists():
        _usage(script, f"symbol table '{sym}' not found!")
    if not pages:
        _usage(script, "no pages found!")

    return sym, pages


if __name__ == "__main__":
    sym, pages = _parse_args(sys.argv)
    create_pdf(sym, pages)
