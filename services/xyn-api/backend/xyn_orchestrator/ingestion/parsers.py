from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import BinaryIO

from .interfaces import (
    FILE_KIND_CSV,
    FILE_KIND_GEOJSON,
    FILE_KIND_JSON,
    FILE_KIND_TSV,
    FILE_KIND_SHP,
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
    version: str = "1.0"
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
                    provenance={"row_number": index},
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
    version: str = "1.0"
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
                        provenance={"feature_index": index},
                        record_index=index,
                    )
                )
        elif isinstance(parsed, dict):
            records.append(
                ParsedRecordEnvelope(
                    source_payload=parsed,
                    normalized_payload={"document": parsed},
                    source_schema={"geojson_type": str(parsed.get("type") or "")},
                    provenance={"feature_index": 1},
                    record_index=1,
                )
            )
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="1",
            records=tuple(records),
        )


@dataclass(frozen=True)
class UnsupportedGroupedShapefileParser:
    name: str = "shapefile_grouped_unsupported"
    version: str = "0"
    supported_kinds: tuple[str, ...] = (FILE_KIND_SHP,)

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        return ParseOutcome(
            parser_name=self.name,
            parser_version=self.version,
            normalization_version="0",
            records=tuple(),
            warnings=("shapefile parsing not implemented in this runtime",),
        )


def build_default_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(CsvTsvParser())
    registry.register(GeoJsonParser())
    registry.register(UnsupportedGroupedShapefileParser())
    return registry
