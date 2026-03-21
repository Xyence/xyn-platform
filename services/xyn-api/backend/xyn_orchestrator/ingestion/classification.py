from __future__ import annotations

from pathlib import Path

from .interfaces import (
    FILE_KIND_ACCDB,
    FILE_KIND_CPG,
    FILE_KIND_CSV,
    FILE_KIND_DBF,
    FILE_KIND_FILE_GDB,
    FILE_KIND_GDBTABLE,
    FILE_KIND_GEOJSON,
    FILE_KIND_JSON,
    FILE_KIND_MDB,
    FILE_KIND_PDF,
    FILE_KIND_PRJ,
    FILE_KIND_SHP,
    FILE_KIND_SHX,
    FILE_KIND_TSV,
    FILE_KIND_UNKNOWN_BINARY,
    FILE_KIND_XLS,
    FILE_KIND_XLSX,
    FILE_KIND_XML,
    FILE_KIND_ZIP,
    FileClassification,
)

_EXTENSION_TO_KIND = {
    "zip": FILE_KIND_ZIP,
    "csv": FILE_KIND_CSV,
    "tsv": FILE_KIND_TSV,
    "geojson": FILE_KIND_GEOJSON,
    "json": FILE_KIND_JSON,
    "xlsx": FILE_KIND_XLSX,
    "xls": FILE_KIND_XLS,
    "shp": FILE_KIND_SHP,
    "dbf": FILE_KIND_DBF,
    "shx": FILE_KIND_SHX,
    "prj": FILE_KIND_PRJ,
    "cpg": FILE_KIND_CPG,
    "mdb": FILE_KIND_MDB,
    "accdb": FILE_KIND_ACCDB,
    "xml": FILE_KIND_XML,
    "pdf": FILE_KIND_PDF,
    "gdb": FILE_KIND_FILE_GDB,
    "gdbtable": FILE_KIND_GDBTABLE,
}


def _group_key(path: str) -> str:
    p = Path(str(path or "").strip())
    return p.stem.lower()


def classify_file(*, filename: str, content_type: str = "") -> FileClassification:
    token = str(filename or "").strip().lower()
    if ".gdb/" in token or token.endswith(".gdb"):
        ext = "gdbtable" if token.endswith(".gdbtable") else "gdb"
        kind = FILE_KIND_GDBTABLE if ext == "gdbtable" else FILE_KIND_FILE_GDB
        return FileClassification(kind=kind, extension=ext, group_key=_group_key(token), mime_type=str(content_type or "").strip().lower())
    ext = ""
    if "." in token:
        ext = token.rsplit(".", 1)[-1]
    kind = _EXTENSION_TO_KIND.get(ext, FILE_KIND_UNKNOWN_BINARY)
    mime = str(content_type or "").strip().lower()
    if kind == FILE_KIND_UNKNOWN_BINARY and mime:
        if "zip" in mime:
            kind = FILE_KIND_ZIP
        elif "csv" in mime:
            kind = FILE_KIND_CSV
        elif "json" in mime:
            kind = FILE_KIND_JSON
        elif "xml" in mime:
            kind = FILE_KIND_XML
        elif "pdf" in mime:
            kind = FILE_KIND_PDF
    return FileClassification(kind=kind, extension=ext, group_key=_group_key(token), mime_type=mime)
