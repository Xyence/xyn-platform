from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
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
    TARGET_TYPE_GROUPED,
    FILE_KIND_TSV,
    FILE_KIND_XLS,
    FILE_KIND_XLSX,
    FILE_KIND_XML,
    ISSUE_CATEGORY_INVALID_GROUPED_INPUT,
    ISSUE_CATEGORY_NOT_INSTALLED,
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


def _load_pyshp_module():
    try:
        import shapefile as pyshp  # type: ignore
    except Exception:
        return None
    return pyshp


def _mdb_tools_available() -> bool:
    return bool(shutil.which("mdb-tables") and shutil.which("mdb-export"))


def _run_mdb_command(args: list[str]):
    return subprocess.run(args, capture_output=True, text=True, check=False)


@dataclass(frozen=True)
class CsvTsvParser:
    name: str = "csv_tsv_parser"
    version: str = "1.1"
    supported_kinds: tuple[str, ...] = (FILE_KIND_CSV, FILE_KIND_TSV)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        raw_limit = str(os.environ.get("XYN_INGEST_DELIMITED_MAX_RECORDS") or "50000").strip()
        try:
            max_records = max(1000, min(int(raw_limit), 2_000_000))
        except ValueError:
            max_records = 50000
        payload = stream.read()
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload or b"")
        text = payload.decode("utf-8", errors="replace")
        kind = str(target.classified_kind or "").strip().lower()
        delimiter = "\t" if kind == FILE_KIND_TSV else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        records: list[ParsedRecordEnvelope] = []
        issues: list[ParseIssue] = []
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
            if index >= max_records:
                issues.append(
                    ParseIssue(
                        category=ISSUE_CATEGORY_PARSE_ERROR,
                        code="delimited.record_limit_reached",
                        message=f"delimited parse truncated after {max_records} rows",
                        severity="warning",
                        details={"max_records": max_records},
                    )
                )
                break
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="1",
            records=tuple(records),
            issues=tuple(issues),
            warnings=tuple(issue.message for issue in issues if issue.severity != "error"),
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
class ShapefileParser:
    name: str = "shapefile_parser"
    version: str = "1.0"
    supported_kinds: tuple[str, ...] = (FILE_KIND_SHP,)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        raw_limit = str(os.environ.get("XYN_INGEST_SHAPEFILE_MAX_FEATURES") or "50000").strip()
        try:
            max_features = max(1000, min(int(raw_limit), 2_000_000))
        except ValueError:
            max_features = 50000
        members = set(target.grouped_member_paths or tuple())
        required = {".shp", ".dbf", ".shx"}
        have = {f".{path.rsplit('.', 1)[-1].lower()}" for path in members if "." in path}
        if str(target.target_type or "") != TARGET_TYPE_GROUPED:
            return ParseOutcome(
                parser_name=self.name,
                parser_version=self.version,
                normalization_version="1",
                records=tuple(),
                issues=(
                    ParseIssue(
                        category=ISSUE_CATEGORY_INVALID_GROUPED_INPUT,
                        code="shapefile.grouped_target_required",
                        message="shapefile parsing requires grouped target metadata",
                        severity="warning",
                    ),
                ),
                warnings=("shapefile parsing requires grouped target metadata",),
            )
        if not required.issubset(have):
            return ParseOutcome(
                parser_name=self.name,
                parser_version=self.version,
                normalization_version="1",
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
        pyshp = _load_pyshp_module()
        if pyshp is None:
            return ParseOutcome(
                parser_name=self.name,
                parser_version=self.version,
                normalization_version="1",
                records=tuple(),
                issues=(
                    ParseIssue(
                        category=ISSUE_CATEGORY_NOT_INSTALLED,
                        code="shapefile.pyshp_missing",
                        message="pyshp dependency is not installed",
                        severity="warning",
                    ),
                ),
                warnings=("pyshp dependency is not installed",),
            )
        member_bytes = target.metadata.get("grouped_member_bytes") if isinstance(target.metadata, dict) else {}
        if not isinstance(member_bytes, dict):
            member_bytes = {}

        records: list[ParsedRecordEnvelope] = []
        issues: list[ParseIssue] = []
        try:
            with tempfile.TemporaryDirectory(prefix="xyn-shp-") as tmp_dir:
                grouped_paths = list(target.grouped_member_paths or tuple())
                for member_path in grouped_paths:
                    content = member_bytes.get(member_path)
                    if not isinstance(content, (bytes, bytearray)):
                        continue
                    rel = Path(str(member_path).replace("\\", "/"))
                    safe_rel = Path(*[part for part in rel.parts if part not in ("..", "/")])
                    local_path = Path(tmp_dir) / safe_rel
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_path, "wb") as fp:
                        fp.write(bytes(content))

                def _path_for(ext: str) -> str:
                    for p in grouped_paths:
                        if p.lower().endswith(ext):
                            return str(Path(tmp_dir) / Path(p))
                    return ""

                shp_path = _path_for(".shp")
                dbf_path = _path_for(".dbf")
                shx_path = _path_for(".shx")
                prj_path = _path_for(".prj")
                cpg_path = _path_for(".cpg")
                encoding = "utf-8"
                if cpg_path and os.path.exists(cpg_path):
                    try:
                        with open(cpg_path, "r", encoding="utf-8", errors="replace") as fp:
                            cpg_token = str(fp.read().strip() or "").replace("-", "").lower()
                        if cpg_token in {"utf8", "utf_8"}:
                            encoding = "utf-8"
                        elif cpg_token:
                            encoding = cpg_token
                    except Exception:
                        encoding = "utf-8"

                reader = pyshp.Reader(shp=shp_path, dbf=dbf_path, shx=shx_path, encoding=encoding)
                field_names = [str(field[0]) for field in list(getattr(reader, "fields", []))[1:]]
                crs_wkt = ""
                if prj_path and os.path.exists(prj_path):
                    with open(prj_path, "r", encoding="utf-8", errors="replace") as fp:
                        crs_wkt = str(fp.read().strip() or "")
                if not crs_wkt:
                    issues.append(
                        ParseIssue(
                            category=ISSUE_CATEGORY_PARSE_ERROR,
                            code="shapefile.missing_prj",
                            message="projection (.prj) file missing; CRS metadata unavailable",
                            severity="warning",
                        )
                    )

                feature_index = 0
                for feature_index, shape_record in enumerate(reader.shapeRecords(), start=1):
                    shape = getattr(shape_record, "shape", None)
                    record = getattr(shape_record, "record", None)
                    geometry = getattr(shape, "__geo_interface__", None) if shape is not None else None
                    attrs: dict[str, object] = {}
                    if record is not None:
                        values = list(record)
                        for i, field_name in enumerate(field_names):
                            attrs[field_name] = values[i] if i < len(values) else None
                    source_payload = {"attributes": attrs, "geometry": geometry}
                    normalized_payload = {"attributes": attrs, "geometry": geometry}
                    if crs_wkt:
                        normalized_payload["crs_wkt"] = crs_wkt
                    records.append(
                        ParsedRecordEnvelope(
                            source_payload=source_payload,
                            normalized_payload=normalized_payload,
                            source_schema={"fields": field_names, "source_format": "shapefile"},
                            provenance={
                                "feature_index": feature_index,
                                "source_format": "shapefile",
                                "group_key": str(target.group_key or ""),
                                "grouped_member_ids": list(target.grouped_member_ids),
                                "grouped_member_paths": list(target.grouped_member_paths),
                                "crs_present": bool(crs_wkt),
                            },
                            record_index=feature_index,
                        )
                    )
                    if feature_index >= max_features:
                        issues.append(
                            ParseIssue(
                                category=ISSUE_CATEGORY_PARSE_ERROR,
                                code="shapefile.feature_limit_reached",
                                message=f"shapefile parse truncated after {max_features} features",
                                severity="warning",
                                details={"max_features": max_features},
                            )
                        )
                        break
                if feature_index == 0:
                    issues.append(
                        ParseIssue(
                            category=ISSUE_CATEGORY_PARSE_ERROR,
                            code="shapefile.no_features",
                            message="shapefile contained no features",
                            severity="warning",
                        )
                    )
        except Exception as exc:
            return ParseOutcome(
                parser_name=self.name,
                parser_version=self.version,
                normalization_version="1",
                records=tuple(),
                issues=(
                    ParseIssue(
                        category=ISSUE_CATEGORY_PARSE_ERROR,
                        code="shapefile.parse_failed",
                        message=str(exc),
                        severity="error",
                    ),
                ),
                warnings=tuple(),
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
class AccessParser:
    name: str = "access_parser"
    version: str = "1.0"
    supported_kinds: tuple[str, ...] = (FILE_KIND_MDB, FILE_KIND_ACCDB)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        raw_limit = str(os.environ.get("XYN_INGEST_ACCESS_MAX_RECORDS") or "25000").strip()
        try:
            max_records = max(1000, min(int(raw_limit), 1_000_000))
        except ValueError:
            max_records = 25000
        if not _mdb_tools_available():
            return ParseOutcome(
                parser_name=self.name,
                parser_version=self.version,
                normalization_version="1",
                records=tuple(),
                issues=(
                    ParseIssue(
                        category=ISSUE_CATEGORY_NOT_INSTALLED,
                        code="access.mdbtools_missing",
                        message="mdbtools (mdb-tables, mdb-export) is not installed",
                        severity="warning",
                    ),
                ),
                warnings=("mdbtools (mdb-tables, mdb-export) is not installed",),
            )

        payload = stream.read()
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload or b"")
        ext = ".accdb" if str(target.classified_kind or "").strip().lower() == FILE_KIND_ACCDB else ".mdb"
        records: list[ParsedRecordEnvelope] = []
        issues: list[ParseIssue] = []
        try:
            with tempfile.TemporaryDirectory(prefix="xyn-access-") as tmp_dir:
                db_path = str(Path(tmp_dir) / f"source{ext}")
                with open(db_path, "wb") as fp:
                    fp.write(bytes(payload))
                list_cmd = _run_mdb_command(["mdb-tables", "-1", db_path])
                if int(list_cmd.returncode or 0) != 0:
                    return ParseOutcome(
                        parser_name=self.name,
                        parser_version=self.version,
                        normalization_version="1",
                        records=tuple(),
                        issues=(
                            ParseIssue(
                                category=ISSUE_CATEGORY_PARSE_ERROR,
                                code="access.table_list_failed",
                                message=str(list_cmd.stderr or list_cmd.stdout or "failed to list Access tables").strip(),
                                severity="error",
                            ),
                        ),
                        warnings=tuple(),
                    )
                tables = [str(line).strip() for line in str(list_cmd.stdout or "").splitlines() if str(line).strip()]
                if not tables:
                    issues.append(
                        ParseIssue(
                            category=ISSUE_CATEGORY_PARSE_ERROR,
                            code="access.no_tables",
                            message="access database contained no tables",
                            severity="warning",
                        )
                    )
                record_index = 0
                truncated = False
                for table in tables:
                    export_proc = subprocess.Popen(
                        ["mdb-export", db_path, table],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    if export_proc.stdout is None:
                        issues.append(
                            ParseIssue(
                                category=ISSUE_CATEGORY_PARSE_ERROR,
                                code="access.table_export_failed",
                                message=f"failed to export table '{table}'",
                                severity="warning",
                                details={"table": table, "stderr": "mdb-export produced no stdout stream"},
                            )
                        )
                        continue
                    reader = csv.DictReader(export_proc.stdout)
                    for row_number, row in enumerate(reader, start=1):
                        record_index += 1
                        row_data = {str(k): row.get(k) for k in (row.keys() if row else [])}
                        records.append(
                            ParsedRecordEnvelope(
                                source_payload={"table": table, "row": row_data},
                                normalized_payload={"table": table, "fields": row_data},
                                source_schema={"columns": list(row.keys()) if row else [], "table": table},
                                provenance={"table": table, "row_number": row_number, "source_format": "access"},
                                record_index=record_index,
                            )
                        )
                        if record_index >= max_records:
                            issues.append(
                                ParseIssue(
                                    category=ISSUE_CATEGORY_PARSE_ERROR,
                                    code="access.record_limit_reached",
                                    message=f"access parse truncated after {max_records} rows",
                                    severity="warning",
                                    details={"max_records": max_records},
                                )
                            )
                            truncated = True
                            break
                    export_proc.stdout.close()
                    stderr_text = str(export_proc.stderr.read() or "").strip() if export_proc.stderr else ""
                    return_code = int(export_proc.wait() or 0)
                    if return_code != 0:
                        issues.append(
                            ParseIssue(
                                category=ISSUE_CATEGORY_PARSE_ERROR,
                                code="access.table_export_failed",
                                message=f"failed to export table '{table}'",
                                severity="warning",
                                details={"table": table, "stderr": stderr_text},
                            )
                        )
                    if export_proc.stderr:
                        export_proc.stderr.close()
                    if truncated:
                        break
        except Exception as exc:
            return ParseOutcome(
                parser_name=self.name,
                parser_version=self.version,
                normalization_version="1",
                records=tuple(),
                issues=(
                    ParseIssue(
                        category=ISSUE_CATEGORY_PARSE_ERROR,
                        code="access.parse_failed",
                        message=str(exc),
                        severity="error",
                    ),
                ),
                warnings=tuple(),
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
    registry.register(ShapefileParser())
    registry.register(AccessParser())
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
    return registry
