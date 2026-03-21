from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import BinaryIO

from .interfaces import (
    FILE_KIND_ACCDB,
    FILE_KIND_CSV,
    FILE_KIND_FILE_GDB,
    FILE_KIND_GDBTABLE,
    FILE_KIND_GEOJSON,
    FILE_KIND_JSON,
    FILE_KIND_MDB,
    FILE_KIND_SHP,
    FILE_KIND_TSV,
    FILE_KIND_XLS,
    FILE_KIND_XLSX,
    FILE_KIND_XML,
    ISSUE_CATEGORY_INVALID_GROUPED_INPUT,
    ISSUE_CATEGORY_NOT_IMPLEMENTED,
    ISSUE_CATEGORY_PARSE_ERROR,
    ISSUE_CATEGORY_UNSUPPORTED_FORMAT,
    ParseIssue,
    ParseOutcome,
    ParseTarget,
    ParsedRecordEnvelope,
)


@dataclass
class ParserRegistry:
    _parsers: dict[str, object]

    def __init__(self) -> None:
        self._parsers = {}

    def register(self, parser) -> None:
        for kind in tuple(getattr(parser, "supported_kinds", tuple())):
            self._parsers[str(kind)] = parser

    def resolve(self, kind: str):
        return self._parsers.get(str(kind or "").strip().lower())

    def supported_kinds(self):
        return sorted(self._parsers.keys())


@dataclass(frozen=True)
class CsvTsvParser:
    name: str = "csv_tsv_parser"
    version: str = "1.1"
    supported_kinds: tuple[str, ...] = (FILE_KIND_CSV, FILE_KIND_TSV)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        payload = stream.read()
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload or b"")
        text = payload.decode("utf-8", errors="replace")
        kind = str(target.classified_kind or "").strip().lower()
        delimiter = "\t" if kind == FILE_KIND_TSV else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        records: list[ParsedRecordEnvelope] = []
        for index, row in enumerate(reader, start=1):
            src = {str(k): row.get(k) for k in row.keys()} if row else {}
            records.append(
                ParsedRecordEnvelope(
                    source_payload=src,
                    normalized_payload={"fields": src},
                    source_schema={"columns": list(row.keys()) if row else []},
                    provenance={"row_number": index, "source_format": kind},
                    record_index=index,
                )
            )
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="1",
            records=tuple(records),
        )


@dataclass(frozen=True)
class GeoJsonParser:
    name: str = "geojson_parser"
    version: str = "1.1"
    supported_kinds: tuple[str, ...] = (FILE_KIND_GEOJSON, FILE_KIND_JSON)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        payload = stream.read()
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload or b"")
        parsed = json.loads(payload.decode("utf-8", errors="replace") or "{}")
        records: list[ParsedRecordEnvelope] = []
        if isinstance(parsed, dict) and str(parsed.get("type") or "").lower() == "featurecollection":
            features = parsed.get("features") if isinstance(parsed.get("features"), list) else []
            for index, feature in enumerate(features, start=1):
                if not isinstance(feature, dict):
                    continue
                properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else None
                records.append(
                    ParsedRecordEnvelope(
                        source_payload=feature,
                        normalized_payload={
                            "properties": properties,
                            "geometry": geometry,
                        },
                        source_schema={"geojson_type": "Feature"},
                        provenance={"feature_index": index, "source_format": "geojson"},
                        record_index=index,
                    )
                )
        elif isinstance(parsed, dict):
            records.append(
                ParsedRecordEnvelope(
                    source_payload=parsed,
                    normalized_payload={"document": parsed},
                    source_schema={"geojson_type": str(parsed.get("type") or "")},
                    provenance={"feature_index": 1, "source_format": "json"},
                    record_index=1,
                )
            )
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="1",
            records=tuple(records),
        )


def _col_to_index(ref: str) -> int:
    token = re.sub(r"[^A-Z]", "", str(ref or "").upper())
    if not token:
        return 0
    value = 0
    for char in token:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return max(0, value - 1)


def _xlsx_read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return []
    root = ET.fromstring(archive.read(path))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values: list[str] = []
    for node in root.findall("x:si", ns):
        chunks: list[str] = []
        direct_t = node.find("x:t", ns)
        if direct_t is not None and direct_t.text is not None:
            chunks.append(direct_t.text)
        for tnode in node.findall(".//x:r/x:t", ns):
            if tnode.text is not None:
                chunks.append(tnode.text)
        values.append("".join(chunks))
    return values


def _xlsx_read_workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
    rels_xml = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    ns_main = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ns_rel = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    ns_pkg = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    rels: dict[str, str] = {}
    for rel in rels_xml.findall("p:Relationship", ns_pkg):
        rid = str(rel.attrib.get("Id") or "")
        target = str(rel.attrib.get("Target") or "")
        if rid and target:
            rels[rid] = target
    rows: list[tuple[str, str]] = []
    for sheet in workbook_xml.findall("x:sheets/x:sheet", ns_main):
        name = str(sheet.attrib.get("name") or "Sheet")
        rid = str(sheet.attrib.get("{%s}id" % ns_rel["r"]) or "")
        target = rels.get(rid, "")
        if target:
            path = target if target.startswith("xl/") else f"xl/{target}"
            rows.append((name, path))
    return rows


@dataclass(frozen=True)
class XlsxParser:
    name: str = "xlsx_parser"
    version: str = "1.0"
    supported_kinds: tuple[str, ...] = (FILE_KIND_XLSX,)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        payload = stream.read()
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload or b"")
        records: list[ParsedRecordEnvelope] = []
        issues: list[ParseIssue] = []
        try:
            with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
                if "xl/workbook.xml" not in archive.namelist():
                    raise ValueError("missing workbook.xml")
                shared = _xlsx_read_shared_strings(archive)
                sheets = _xlsx_read_workbook_sheets(archive)
                for sheet_name, sheet_path in sheets:
                    if sheet_path not in archive.namelist():
                        issues.append(
                            ParseIssue(
                                category=ISSUE_CATEGORY_PARSE_ERROR,
                                code="xlsx.sheet_missing",
                                message=f"worksheet '{sheet_name}' target missing",
                                severity="warning",
                            )
                        )
                        continue
                    root = ET.fromstring(archive.read(sheet_path))
                    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    rows = root.findall("x:sheetData/x:row", ns)
                    headers: list[str] = []
                    for row_node in rows:
                        row_index = int(str(row_node.attrib.get("r") or "0") or "0")
                        raw_cells = row_node.findall("x:c", ns)
                        values: dict[int, str] = {}
                        for c in raw_cells:
                            ref = str(c.attrib.get("r") or "")
                            col_index = _col_to_index(ref)
                            cell_type = str(c.attrib.get("t") or "")
                            if cell_type == "inlineStr":
                                node = c.find("x:is/x:t", ns)
                                value = str(node.text or "") if node is not None else ""
                            else:
                                value_node = c.find("x:v", ns)
                                value = str(value_node.text or "") if value_node is not None else ""
                                if cell_type == "s" and value.isdigit():
                                    idx = int(value)
                                    value = shared[idx] if 0 <= idx < len(shared) else ""
                            values[col_index] = value
                        if row_index == 1:
                            if values:
                                headers = [values.get(i, f"column_{i+1}").strip() or f"column_{i+1}" for i in sorted(values.keys())]
                            continue
                        if not values:
                            continue
                        if not headers:
                            headers = [f"column_{i+1}" for i in sorted(values.keys())]
                        normalized: dict[str, str] = {}
                        for idx, header in enumerate(headers):
                            normalized[str(header)] = values.get(idx, "")
                        source_payload = {
                            "sheet": sheet_name,
                            "row_number": row_index,
                            "cells": {str(k): v for k, v in values.items()},
                        }
                        records.append(
                            ParsedRecordEnvelope(
                                source_payload=source_payload,
                                normalized_payload={"fields": normalized},
                                source_schema={"columns": headers, "sheet": sheet_name},
                                provenance={"sheet": sheet_name, "row_number": row_index, "source_format": "xlsx"},
                                record_index=row_index,
                            )
                        )
        except zipfile.BadZipFile:
            issues.append(
                ParseIssue(
                    category=ISSUE_CATEGORY_PARSE_ERROR,
                    code="xlsx.invalid_zip",
                    message="invalid XLSX archive",
                    severity="error",
                )
            )
        except Exception as exc:
            issues.append(
                ParseIssue(
                    category=ISSUE_CATEGORY_PARSE_ERROR,
                    code="xlsx.parse_failed",
                    message=str(exc),
                    severity="error",
                )
            )
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="1",
            records=tuple(records),
            issues=tuple(issues),
            warnings=tuple(issue.message for issue in issues if issue.severity != "error"),
        )


@dataclass(frozen=True)
class UnsupportedFormatParser:
    name: str
    version: str
    supported_kinds: tuple[str, ...]
    category: str
    code: str
    message: str

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="0",
            records=tuple(),
            issues=(
                ParseIssue(
                    category=self.category,
                    code=self.code,
                    message=self.message,
                    severity="warning",
                ),
            ),
            warnings=(self.message,),
        )


@dataclass(frozen=True)
class UnsupportedGroupedShapefileParser:
    name: str = "shapefile_grouped_unsupported"
    version: str = "0"
    supported_kinds: tuple[str, ...] = (FILE_KIND_SHP,)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        members = set(target.grouped_member_paths)
        required = {".shp", ".dbf", ".shx"}
        have = {f".{path.rsplit('.', 1)[-1].lower()}" for path in members if "." in path}
        if not required.issubset(have):
            return ParseOutcome(
                parser_name=self.name,
                parser_version=self.version,
                normalization_version="0",
                records=tuple(),
                issues=(
                    ParseIssue(
                        category=ISSUE_CATEGORY_INVALID_GROUPED_INPUT,
                        code="shapefile.missing_required_members",
                        message="grouped shapefile bundle missing required components (.shp/.dbf/.shx)",
                        severity="warning",
                        details={"required": sorted(required), "have": sorted(have)},
                    ),
                ),
                warnings=("grouped shapefile bundle missing required members",),
            )
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="0",
            records=tuple(),
            issues=(
                ParseIssue(
                    category=ISSUE_CATEGORY_NOT_IMPLEMENTED,
                    code="shapefile.not_implemented",
                    message="shapefile parsing not implemented in this runtime",
                    severity="warning",
                ),
            ),
            warnings=("shapefile parsing not implemented in this runtime",),
        )


def build_default_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(CsvTsvParser())
    registry.register(GeoJsonParser())
    registry.register(XlsxParser())
    registry.register(UnsupportedGroupedShapefileParser())
    registry.register(
        UnsupportedFormatParser(
            name="xls_unsupported",
            version="1",
            supported_kinds=(FILE_KIND_XLS,),
            category=ISSUE_CATEGORY_NOT_IMPLEMENTED,
            code="xls.not_implemented",
            message="xls parsing not implemented",
        )
    )
    registry.register(
        UnsupportedFormatParser(
            name="access_unsupported",
            version="1",
            supported_kinds=(FILE_KIND_MDB, FILE_KIND_ACCDB),
            category=ISSUE_CATEGORY_NOT_IMPLEMENTED,
            code="access.not_implemented",
            message="mdb/accdb parsing not implemented",
        )
    )
    registry.register(
        UnsupportedFormatParser(
            name="xml_unsupported",
            version="1",
            supported_kinds=(FILE_KIND_XML,),
            category=ISSUE_CATEGORY_UNSUPPORTED_FORMAT,
            code="xml.unsupported",
            message="xml parsing is unsupported in this runtime",
        )
    )
    registry.register(
        UnsupportedFormatParser(
            name="file_gdb_unsupported",
            version="1",
            supported_kinds=(FILE_KIND_FILE_GDB, FILE_KIND_GDBTABLE),
            category=ISSUE_CATEGORY_NOT_IMPLEMENTED,
            code="file_gdb.not_implemented",
            message="file geodatabase parsing not implemented",
        )
    )
    return registry
