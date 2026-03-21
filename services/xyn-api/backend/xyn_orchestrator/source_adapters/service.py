from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from django.db import transaction

from xyn_orchestrator import models

from .interfaces import (
    ADAPTER_STATUS_ERROR,
    ADAPTER_STATUS_OK,
    ADAPTER_STATUS_UNSUPPORTED,
    ADAPTER_STATUS_WARNING,
    AdaptationOutcome,
    AdaptedRecordEnvelope,
    AdapterContext,
    ParsedRecordAdapter,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _sorted_json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _get_by_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for token in [part.strip() for part in str(path or "").split(".") if part.strip()]:
        if not isinstance(current, dict):
            return None
        current = current.get(token)
    return current


def _infer_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"


def _collect_arcgis_field_hints(*, features: list[dict[str, Any]], field_definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for entry in field_definitions:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        by_name[name] = {
            "name": name,
            "inferred_type": str(entry.get("type") or "").strip().lower() or "unknown",
            "alias": str(entry.get("alias") or "").strip(),
        }
    for feature in features:
        attrs = _safe_dict(feature.get("attributes"))
        for key, value in attrs.items():
            row = by_name.setdefault(str(key), {"name": str(key), "inferred_type": "unknown", "alias": ""})
            inferred = _infer_type(value)
            if row.get("inferred_type") in {"unknown", "", None} and inferred != "null":
                row["inferred_type"] = inferred
    return sorted(by_name.values(), key=lambda item: item["name"])


@dataclass(frozen=True)
class CsvAdapter:
    name: str = "csv_source_adapter"
    version: str = "1.0"
    adapter_kind: str = "csv"

    def supports(self, *, context: AdapterContext) -> bool:
        source_format = str(_safe_dict(context.parsed_row.provenance_json).get("source_format") or "").lower()
        return context.parsed_row.parser_name == "csv_tsv_parser" or source_format in {"csv", "tsv"}

    def adapt(self, *, context: AdapterContext) -> AdaptationOutcome:
        normalized = _safe_dict(context.parsed_row.normalized_payload_json)
        fields = _safe_dict(normalized.get("fields"))
        source_schema = _safe_dict(context.parsed_row.source_schema_json)
        columns = [str(item) for item in _safe_list(source_schema.get("columns")) if str(item).strip()]
        field_metadata = [{"name": name, "inferred_type": _infer_type(fields.get(name))} for name in columns]
        if not field_metadata:
            field_metadata = [{"name": key, "inferred_type": _infer_type(value)} for key, value in fields.items()]
        provenance = _safe_dict(context.parsed_row.provenance_json)
        source_format = str(provenance.get("source_format") or "csv").lower()
        return AdaptationOutcome(
            adapter_name=self.name,
            adapter_version=self.version,
            records=(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format=source_format,
                    adapted_payload={"record": fields},
                    field_metadata=field_metadata,
                    schema_hints={"columns": [item.get("name") for item in field_metadata], "header_present": bool(columns)},
                    source_position={
                        "row_number": provenance.get("row_number"),
                        "record_index": context.parsed_row.record_index,
                    },
                    provenance={"parsed_record_id": str(context.parsed_row.id), "source_format": source_format},
                    warnings=[],
                    findings=[],
                    status=ADAPTER_STATUS_OK,
                    record_index=context.parsed_row.record_index,
                ),
            ),
        )


@dataclass(frozen=True)
class ShapefileAdapter:
    name: str = "shapefile_source_adapter"
    version: str = "1.0"
    adapter_kind: str = "shapefile"

    def supports(self, *, context: AdapterContext) -> bool:
        source_format = str(_safe_dict(context.parsed_row.provenance_json).get("source_format") or "").lower()
        return context.parsed_row.parser_name == "shapefile_parser" or source_format == "shapefile"

    def adapt(self, *, context: AdapterContext) -> AdaptationOutcome:
        normalized = _safe_dict(context.parsed_row.normalized_payload_json)
        attributes = _safe_dict(normalized.get("attributes"))
        geometry = normalized.get("geometry")
        source_schema = _safe_dict(context.parsed_row.source_schema_json)
        fields = [str(name) for name in _safe_list(source_schema.get("fields")) if str(name).strip()]
        provenance = _safe_dict(context.parsed_row.provenance_json)
        crs_wkt = str(normalized.get("crs_wkt") or "").strip()
        warnings: list[dict[str, Any]] = []
        if not crs_wkt:
            warnings.append(
                {
                    "code": "adapter.shapefile.missing_crs",
                    "message": "CRS metadata is missing for this shapefile record.",
                }
            )
        return AdaptationOutcome(
            adapter_name=self.name,
            adapter_version=self.version,
            records=(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format="shapefile",
                    adapted_payload={"attributes": attributes, "geometry": geometry},
                    geometry_payload=geometry if isinstance(geometry, dict) else None,
                    field_metadata=[{"name": name, "inferred_type": _infer_type(attributes.get(name))} for name in fields],
                    schema_hints={"fields": fields, "crs_wkt": crs_wkt},
                    source_position={
                        "feature_index": provenance.get("feature_index"),
                        "record_index": context.parsed_row.record_index,
                    },
                    provenance={
                        "parsed_record_id": str(context.parsed_row.id),
                        "group_key": provenance.get("group_key"),
                        "grouped_member_ids": _safe_list(provenance.get("grouped_member_ids")),
                        "grouped_member_paths": _safe_list(provenance.get("grouped_member_paths")),
                    },
                    warnings=warnings,
                    findings=[],
                    status=ADAPTER_STATUS_WARNING if warnings else ADAPTER_STATUS_OK,
                    failure_reason="missing shapefile CRS metadata" if warnings else "",
                    record_index=context.parsed_row.record_index,
                ),
            ),
            warnings=tuple(item["message"] for item in warnings),
        )


@dataclass(frozen=True)
class AccessAdapter:
    name: str = "access_source_adapter"
    version: str = "1.0"
    adapter_kind: str = "access"

    def supports(self, *, context: AdapterContext) -> bool:
        source_format = str(_safe_dict(context.parsed_row.provenance_json).get("source_format") or "").lower()
        return context.parsed_row.parser_name == "access_parser" or source_format == "access"

    def adapt(self, *, context: AdapterContext) -> AdaptationOutcome:
        normalized = _safe_dict(context.parsed_row.normalized_payload_json)
        table_name = str(normalized.get("table") or _safe_dict(context.parsed_row.provenance_json).get("table") or "table")
        fields = _safe_dict(normalized.get("fields"))
        source_schema = _safe_dict(context.parsed_row.source_schema_json)
        columns = [str(item) for item in _safe_list(source_schema.get("columns")) if str(item).strip()]
        if not columns:
            columns = list(fields.keys())
        provenance = _safe_dict(context.parsed_row.provenance_json)
        return AdaptationOutcome(
            adapter_name=self.name,
            adapter_version=self.version,
            records=(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format="access",
                    source_subtype=table_name,
                    adapted_payload={"table": table_name, "record": fields},
                    field_metadata=[{"name": col, "inferred_type": _infer_type(fields.get(col))} for col in columns],
                    schema_hints={"table": table_name, "columns": columns},
                    source_position={
                        "table": table_name,
                        "row_number": provenance.get("row_number"),
                        "record_index": context.parsed_row.record_index,
                    },
                    provenance={"parsed_record_id": str(context.parsed_row.id), "table": table_name},
                    warnings=[],
                    findings=[],
                    status=ADAPTER_STATUS_OK,
                    record_index=context.parsed_row.record_index,
                ),
            ),
        )


@dataclass(frozen=True)
class DbfAdapter:
    name: str = "dbf_source_adapter"
    version: str = "1.0"
    adapter_kind: str = "dbf"

    def supports(self, *, context: AdapterContext) -> bool:
        source_format = str(_safe_dict(context.parsed_row.provenance_json).get("source_format") or "").lower()
        parsed_format = str(_safe_dict(context.parsed_row.source_schema_json).get("source_format") or "").lower()
        return source_format == "dbf" or parsed_format == "dbf" or context.parsed_row.parser_name == "dbf_parser"

    def adapt(self, *, context: AdapterContext) -> AdaptationOutcome:
        normalized = _safe_dict(context.parsed_row.normalized_payload_json)
        fields = _safe_dict(normalized.get("fields") or normalized.get("attributes"))
        warnings: list[dict[str, Any]] = []
        status = ADAPTER_STATUS_OK
        failure_reason = ""
        if not fields:
            status = ADAPTER_STATUS_UNSUPPORTED
            failure_reason = "standalone DBF adapter requires tabular parsed payload"
            warnings.append(
                {
                    "code": "adapter.dbf.parsed_payload_missing",
                    "message": failure_reason,
                    "category": "not_implemented",
                }
            )
        field_metadata = [{"name": key, "inferred_type": _infer_type(value)} for key, value in fields.items()]
        provenance = _safe_dict(context.parsed_row.provenance_json)
        return AdaptationOutcome(
            adapter_name=self.name,
            adapter_version=self.version,
            records=(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format="dbf",
                    adapted_payload={"record": fields},
                    field_metadata=field_metadata,
                    schema_hints={"columns": [item["name"] for item in field_metadata]},
                    source_position={"row_number": provenance.get("row_number"), "record_index": context.parsed_row.record_index},
                    provenance={"parsed_record_id": str(context.parsed_row.id)},
                    warnings=warnings,
                    findings=[],
                    status=status,
                    failure_reason=failure_reason,
                    record_index=context.parsed_row.record_index,
                ),
            ),
            warnings=tuple(item["message"] for item in warnings),
        )


@dataclass(frozen=True)
class JsonHttpAdapter:
    name: str = "json_http_source_adapter"
    version: str = "1.0"
    adapter_kind: str = "json_http"

    def supports(self, *, context: AdapterContext) -> bool:
        source_format = str(_safe_dict(context.parsed_row.provenance_json).get("source_format") or "").lower()
        if source_format in {"json", "geojson"}:
            return True
        return context.parsed_row.parser_name == "geojson_parser"

    def adapt(self, *, context: AdapterContext) -> AdaptationOutcome:
        connector_config = _safe_dict(context.source_connector.configuration_json)
        adapter_config = _safe_dict(connector_config.get("json_adapter"))
        path = str(adapter_config.get("record_path") or "").strip()

        normalized = _safe_dict(context.parsed_row.normalized_payload_json)
        source_payload = _safe_dict(context.parsed_row.source_payload_json)
        provenance = _safe_dict(context.parsed_row.provenance_json)
        source_format = str(provenance.get("source_format") or "").lower() or "json"

        records: list[AdaptedRecordEnvelope] = []
        warnings: list[str] = []
        if "properties" in normalized and "geometry" in normalized:
            properties = _safe_dict(normalized.get("properties"))
            geometry = normalized.get("geometry")
            records.append(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format="geojson",
                    source_subtype="feature",
                    adapted_payload={"record": properties, "geometry": geometry},
                    geometry_payload=geometry if isinstance(geometry, dict) else None,
                    field_metadata=[{"name": key, "inferred_type": _infer_type(value)} for key, value in properties.items()],
                    schema_hints={"record_shape": "geojson_feature"},
                    source_position={"feature_index": provenance.get("feature_index"), "record_index": context.parsed_row.record_index},
                    provenance={"parsed_record_id": str(context.parsed_row.id)},
                    warnings=[],
                    findings=[],
                    status=ADAPTER_STATUS_OK,
                    record_index=context.parsed_row.record_index,
                )
            )
            return AdaptationOutcome(
                adapter_name=self.name,
                adapter_version=self.version,
                records=tuple(records),
            )

        root_document = _safe_dict(normalized.get("document") or source_payload)
        extracted = _get_by_path(root_document, path) if path else root_document
        if isinstance(extracted, list):
            iterable = [item for item in extracted if isinstance(item, dict)]
        elif isinstance(extracted, dict):
            iterable = [extracted]
        else:
            iterable = []

        if path and not iterable:
            warnings.append(f"json adapter record_path '{path}' did not resolve to records")
        if not iterable and root_document:
            iterable = [root_document]

        for idx, item in enumerate(iterable, start=1):
            records.append(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format=source_format,
                    adapted_payload={"record": item},
                    field_metadata=[{"name": key, "inferred_type": _infer_type(value)} for key, value in item.items()],
                    schema_hints={"record_path": path or "", "record_shape": "object"},
                    source_position={"record_offset": idx, "record_index": context.parsed_row.record_index},
                    provenance={"parsed_record_id": str(context.parsed_row.id), "record_path": path or ""},
                    warnings=[],
                    findings=[],
                    status=ADAPTER_STATUS_OK,
                    record_index=context.parsed_row.record_index,
                )
            )
        if not records:
            records.append(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format=source_format,
                    adapted_payload={"record": {}},
                    field_metadata=[],
                    schema_hints={"record_path": path or "", "record_shape": "empty"},
                    source_position={"record_index": context.parsed_row.record_index},
                    provenance={"parsed_record_id": str(context.parsed_row.id)},
                    warnings=[{"code": "adapter.json.no_records", "message": "No object records could be extracted from JSON payload."}],
                    findings=[],
                    status=ADAPTER_STATUS_WARNING,
                    failure_reason="no extractable JSON records",
                    record_index=context.parsed_row.record_index,
                )
            )
        return AdaptationOutcome(
            adapter_name=self.name,
            adapter_version=self.version,
            records=tuple(records),
            warnings=tuple(warnings),
        )


@dataclass(frozen=True)
class ArcGisRestJsonAdapter:
    name: str = "arcgis_rest_json_adapter"
    version: str = "1.0"
    adapter_kind: str = "arcgis_rest_json"

    def supports(self, *, context: AdapterContext) -> bool:
        connector_config = _safe_dict(context.source_connector.configuration_json)
        adapter_config = _safe_dict(connector_config.get("json_adapter"))
        forced_kind = str(adapter_config.get("adapter_kind") or "").strip().lower()
        if forced_kind in {"arcgis", "arcgis_rest", "arcgis_rest_json"}:
            return True

        normalized = _safe_dict(context.parsed_row.normalized_payload_json)
        source_payload = _safe_dict(context.parsed_row.source_payload_json)
        root_document = _safe_dict(normalized.get("document") or source_payload)
        if not root_document:
            return False
        if isinstance(root_document.get("error"), dict):
            return True
        features = root_document.get("features")
        if not isinstance(features, list):
            return False
        if "geometryType" in root_document or "spatialReference" in root_document or "fields" in root_document:
            return True
        for feature in features:
            if not isinstance(feature, dict):
                continue
            if "attributes" in feature:
                return True
        return False

    def adapt(self, *, context: AdapterContext) -> AdaptationOutcome:
        connector_config = _safe_dict(context.source_connector.configuration_json)
        adapter_config = _safe_dict(connector_config.get("json_adapter"))
        features_path = str(adapter_config.get("features_path") or "features").strip() or "features"

        normalized = _safe_dict(context.parsed_row.normalized_payload_json)
        source_payload = _safe_dict(context.parsed_row.source_payload_json)
        root_document = _safe_dict(normalized.get("document") or source_payload)
        if not root_document:
            return AdaptationOutcome(
                adapter_name=self.name,
                adapter_version=self.version,
                records=(
                    AdaptedRecordEnvelope(
                        adapter_kind=self.adapter_kind,
                        source_format="arcgis_rest_json",
                        adapted_payload={},
                        schema_hints={},
                        source_position={"record_index": context.parsed_row.record_index},
                        provenance={"parsed_record_id": str(context.parsed_row.id)},
                        warnings=[{"code": "adapter.arcgis.invalid_shape", "message": "ArcGIS payload is missing a root object."}],
                        findings=[],
                        status=ADAPTER_STATUS_UNSUPPORTED,
                        failure_reason="invalid ArcGIS payload shape",
                        record_index=context.parsed_row.record_index,
                    ),
                ),
                warnings=("ArcGIS payload is missing a root object.",),
            )

        error_payload = root_document.get("error")
        if isinstance(error_payload, dict):
            code = str(error_payload.get("code") or "arcgis.error")
            message = str(error_payload.get("message") or "ArcGIS REST error payload encountered.").strip()
            details = _safe_list(error_payload.get("details"))
            return AdaptationOutcome(
                adapter_name=self.name,
                adapter_version=self.version,
                records=(
                    AdaptedRecordEnvelope(
                        adapter_kind=self.adapter_kind,
                        source_format="arcgis_rest_json",
                        source_subtype="error",
                        adapted_payload={"error": error_payload},
                        schema_hints={},
                        source_position={"record_index": context.parsed_row.record_index},
                        provenance={"parsed_record_id": str(context.parsed_row.id)},
                        warnings=[{"code": code, "message": message, "details": details}],
                        findings=[],
                        status=ADAPTER_STATUS_ERROR,
                        failure_reason=message,
                        record_index=context.parsed_row.record_index,
                    ),
                ),
                warnings=(message,),
            )

        features_raw = _get_by_path(root_document, features_path)
        features = [item for item in _safe_list(features_raw) if isinstance(item, dict)]
        if not isinstance(features_raw, list):
            return AdaptationOutcome(
                adapter_name=self.name,
                adapter_version=self.version,
                records=(
                    AdaptedRecordEnvelope(
                        adapter_kind=self.adapter_kind,
                        source_format="arcgis_rest_json",
                        adapted_payload={"document": root_document},
                        schema_hints={"features_path": features_path},
                        source_position={"record_index": context.parsed_row.record_index},
                        provenance={"parsed_record_id": str(context.parsed_row.id), "features_path": features_path},
                        warnings=[{"code": "adapter.arcgis.features_missing", "message": "ArcGIS payload missing feature list."}],
                        findings=[],
                        status=ADAPTER_STATUS_UNSUPPORTED,
                        failure_reason="arcgis feature list missing",
                        record_index=context.parsed_row.record_index,
                    ),
                ),
                warnings=("ArcGIS payload missing feature list.",),
            )

        geometry_type = str(root_document.get("geometryType") or "").strip()
        spatial_reference = _safe_dict(root_document.get("spatialReference"))
        wkid = spatial_reference.get("latestWkid") or spatial_reference.get("wkid")
        field_hints = _collect_arcgis_field_hints(
            features=features,
            field_definitions=[item for item in _safe_list(root_document.get("fields")) if isinstance(item, dict)],
        )
        records: list[AdaptedRecordEnvelope] = []
        if not features:
            records.append(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format="arcgis_rest_json",
                    source_subtype="feature_query",
                    adapted_payload={"features": []},
                    field_metadata=field_hints,
                    schema_hints={
                        "features_path": features_path,
                        "feature_count": 0,
                        "geometry_type": geometry_type,
                        "spatial_reference": spatial_reference,
                        "wkid": wkid,
                    },
                    source_position={"feature_index": None, "record_index": context.parsed_row.record_index},
                    provenance={"parsed_record_id": str(context.parsed_row.id), "features_path": features_path},
                    warnings=[{"code": "adapter.arcgis.empty_features", "message": "ArcGIS payload returned an empty feature set."}],
                    findings=[],
                    status=ADAPTER_STATUS_WARNING,
                    failure_reason="empty feature set",
                    record_index=context.parsed_row.record_index,
                )
            )
            return AdaptationOutcome(
                adapter_name=self.name,
                adapter_version=self.version,
                records=tuple(records),
                warnings=("ArcGIS payload returned an empty feature set.",),
            )

        for index, feature in enumerate(features, start=1):
            attrs = _safe_dict(feature.get("attributes"))
            geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else None
            warnings: list[dict[str, Any]] = []
            if not attrs:
                warnings.append({"code": "adapter.arcgis.attributes_missing", "message": "Feature has no attributes payload."})
            if geometry is None:
                warnings.append({"code": "adapter.arcgis.geometry_missing", "message": "Feature has no geometry payload."})
            status = ADAPTER_STATUS_WARNING if warnings else ADAPTER_STATUS_OK
            failure_reason = "; ".join(item["message"] for item in warnings)
            schema_hints = {
                "features_path": features_path,
                "feature_count": len(features),
                "geometry_type": geometry_type,
                "spatial_reference": spatial_reference,
                "wkid": wkid,
                "display_field_name": str(root_document.get("displayFieldName") or "").strip(),
                "object_id_field_name": str(root_document.get("objectIdFieldName") or "").strip(),
            }
            records.append(
                AdaptedRecordEnvelope(
                    adapter_kind=self.adapter_kind,
                    source_format="arcgis_rest_json",
                    source_subtype="feature_query",
                    adapted_payload={
                        "attributes": attrs,
                        "geometry": geometry,
                        "source_feature": feature,
                    },
                    geometry_payload=geometry if isinstance(geometry, dict) else None,
                    field_metadata=field_hints,
                    schema_hints=schema_hints,
                    source_position={"feature_index": index, "record_index": context.parsed_row.record_index},
                    provenance={
                        "parsed_record_id": str(context.parsed_row.id),
                        "features_path": features_path,
                        "spatial_reference": spatial_reference,
                    },
                    warnings=warnings,
                    findings=[],
                    status=status,
                    failure_reason=failure_reason,
                    record_index=index,
                )
            )
        return AdaptationOutcome(
            adapter_name=self.name,
            adapter_version=self.version,
            records=tuple(records),
            warnings=tuple(
                item.get("message", "")
                for record in records
                for item in record.warnings
                if isinstance(item, dict) and str(item.get("message") or "").strip()
            ),
        )


class SourceAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[ParsedRecordAdapter] = []

    def register(self, adapter: ParsedRecordAdapter) -> None:
        self._adapters.append(adapter)

    def resolve(self, *, context: AdapterContext) -> ParsedRecordAdapter | None:
        for adapter in self._adapters:
            if adapter.supports(context=context):
                return adapter
        return None

    def list_adapters(self) -> list[str]:
        return [adapter.name for adapter in self._adapters]


def build_default_registry() -> SourceAdapterRegistry:
    registry = SourceAdapterRegistry()
    registry.register(ShapefileAdapter())
    registry.register(AccessAdapter())
    registry.register(CsvAdapter())
    registry.register(DbfAdapter())
    registry.register(ArcGisRestJsonAdapter())
    registry.register(JsonHttpAdapter())
    return registry


class SourceAdapterService:
    def __init__(self, *, registry: SourceAdapterRegistry | None = None) -> None:
        self._registry = registry or build_default_registry()

    def adapt_parsed_record(self, *, source_connector: models.SourceConnector, parsed_row: models.IngestParsedRecord) -> list[models.IngestAdaptedRecord]:
        context = AdapterContext(source_connector=source_connector, parsed_row=parsed_row)
        adapter = self._registry.resolve(context=context)
        if adapter is None:
            return []
        outcome = adapter.adapt(context=context)
        persisted: list[models.IngestAdaptedRecord] = []
        for offset, envelope in enumerate(outcome.records, start=1):
            payload_fingerprint = _sorted_json_hash(
                {
                    "adapter_name": outcome.adapter_name,
                    "adapter_version": outcome.adapter_version,
                    "source_format": envelope.source_format,
                    "source_subtype": envelope.source_subtype,
                    "adapted_payload": envelope.adapted_payload,
                    "source_position": envelope.source_position,
                    "record_offset": offset,
                }
            )
            idem = hashlib.sha256(
                (
                    f"adapted|{parsed_row.workspace_id}|{parsed_row.id}|{outcome.adapter_name}|"
                    f"{envelope.source_format}|{offset}|{payload_fingerprint}"
                ).encode("utf-8")
            ).hexdigest()
            row, _ = models.IngestAdaptedRecord.objects.get_or_create(
                workspace=parsed_row.workspace,
                idempotency_key=idem,
                defaults={
                    "source_connector": source_connector,
                    "orchestration_run": parsed_row.orchestration_run,
                    "job_run": parsed_row.job_run,
                    "artifact": parsed_row.artifact,
                    "member": parsed_row.member,
                    "parsed_record": parsed_row,
                    "adapter_name": outcome.adapter_name,
                    "adapter_version": outcome.adapter_version,
                    "adapter_kind": envelope.adapter_kind,
                    "source_format": envelope.source_format,
                    "source_subtype": envelope.source_subtype,
                    "record_index": envelope.record_index,
                    "adapted_payload_json": envelope.adapted_payload,
                    "geometry_payload_json": envelope.geometry_payload if isinstance(envelope.geometry_payload, dict) else {},
                    "field_metadata_json": envelope.field_metadata,
                    "schema_hints_json": envelope.schema_hints,
                    "source_position_json": envelope.source_position,
                    "provenance_json": envelope.provenance,
                    "warnings_json": envelope.warnings,
                    "findings_json": envelope.findings,
                    "status": envelope.status,
                    "failure_reason": envelope.failure_reason,
                },
            )
            persisted.append(row)
        return persisted

    def persist_zip_candidates(
        self,
        *,
        source_connector: models.SourceConnector,
        artifact: models.IngestArtifactRecord,
        members: Iterable[models.IngestArtifactMember],
    ) -> list[models.IngestAdaptedRecord]:
        grouped: dict[str, list[models.IngestArtifactMember]] = {}
        for member in members:
            key = str(member.group_key or member.member_path or member.id)
            grouped.setdefault(key, []).append(member)

        persisted: list[models.IngestAdaptedRecord] = []
        for group_key, rows in grouped.items():
            extensions = sorted({str(item.extension or "").lower() for item in rows if str(item.extension or "").strip()})
            classified_types = sorted({str(item.classified_type or "") for item in rows if str(item.classified_type or "").strip()})
            candidate_kind = "file"
            if {"shp", "dbf", "shx"}.issubset(set(extensions)):
                candidate_kind = "shapefile_bundle"
            elif len(classified_types) == 1:
                candidate_kind = classified_types[0]
            payload = {
                "candidate_kind": candidate_kind,
                "group_key": group_key,
                "member_count": len(rows),
                "member_paths": [str(item.member_path) for item in rows],
                "member_ids": [str(item.id) for item in rows],
                "extensions": extensions,
                "classified_types": classified_types,
            }
            idem = hashlib.sha256(
                (
                    f"zip-candidate|{artifact.workspace_id}|{artifact.id}|{group_key}|{_sorted_json_hash(payload)}"
                ).encode("utf-8")
            ).hexdigest()
            row, _ = models.IngestAdaptedRecord.objects.get_or_create(
                workspace=artifact.workspace,
                idempotency_key=idem,
                defaults={
                    "source_connector": source_connector,
                    "orchestration_run": artifact.orchestration_run,
                    "job_run": artifact.job_run,
                    "artifact": artifact,
                    "adapter_name": "zip_source_adapter",
                    "adapter_version": "1.0",
                    "adapter_kind": "zip",
                    "source_format": "zip",
                    "source_subtype": candidate_kind,
                    "adapted_payload_json": payload,
                    "field_metadata_json": [],
                    "schema_hints_json": {"candidate_kind": candidate_kind},
                    "source_position_json": {"group_key": group_key},
                    "provenance_json": {
                        "member_ids": [str(item.id) for item in rows],
                        "member_paths": [str(item.member_path) for item in rows],
                    },
                    "warnings_json": [],
                    "findings_json": [],
                    "status": ADAPTER_STATUS_OK,
                },
            )
            persisted.append(row)
        return persisted

    def preview_for_source(
        self,
        *,
        source_connector: models.SourceConnector,
        run_id: str = "",
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        queryset = models.IngestAdaptedRecord.objects.filter(source_connector=source_connector).order_by("-created_at", "-id")
        if run_id:
            queryset = queryset.filter(orchestration_run_id=run_id)
        elif source_connector.last_run_id:
            queryset = queryset.filter(orchestration_run_id=source_connector.last_run_id)
        rows = list(queryset[: max(1, int(sample_limit))])
        if not rows:
            return {"record_count": 0, "sample_records": [], "field_hints": [], "warnings": [], "adapter_kinds": []}

        field_hints: dict[str, dict[str, Any]] = {}
        warnings: list[dict[str, Any]] = []
        sample_records: list[dict[str, Any]] = []
        adapter_kinds: set[str] = set()
        source_formats: set[str] = set()
        for row in rows:
            adapter_kinds.add(str(row.adapter_kind or ""))
            source_formats.add(str(row.source_format or ""))
            for item in _safe_list(row.field_metadata_json):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                field_hints.setdefault(name, {"name": name, "inferred_types": set()})
                inferred = str(item.get("inferred_type") or "").strip()
                if inferred:
                    field_hints[name]["inferred_types"].add(inferred)
            for warn in _safe_list(row.warnings_json):
                if isinstance(warn, dict):
                    warnings.append(warn)
            sample_records.append(
                {
                    "id": str(row.id),
                    "adapter_kind": row.adapter_kind,
                    "source_format": row.source_format,
                    "source_subtype": row.source_subtype,
                    "record_index": row.record_index,
                    "payload": _safe_dict(row.adapted_payload_json),
                    "geometry": _safe_dict(row.geometry_payload_json),
                    "source_position": _safe_dict(row.source_position_json),
                    "provenance": _safe_dict(row.provenance_json),
                    "status": row.status,
                    "failure_reason": row.failure_reason or "",
                }
            )
        normalized_hints = [
            {"name": item["name"], "inferred_types": sorted(item["inferred_types"])}
            for item in field_hints.values()
        ]
        normalized_hints.sort(key=lambda item: item["name"])
        arcgis_rows = [row for row in rows if str(row.adapter_kind or "") == "arcgis_rest_json"]
        arcgis_summary: dict[str, Any] = {}
        if arcgis_rows:
            geometry_types = sorted(
                {
                    str(_safe_dict(row.schema_hints_json).get("geometry_type") or "").strip()
                    for row in arcgis_rows
                    if str(_safe_dict(row.schema_hints_json).get("geometry_type") or "").strip()
                }
            )
            wkids = sorted(
                {
                    str(_safe_dict(row.schema_hints_json).get("wkid") or "").strip()
                    for row in arcgis_rows
                    if str(_safe_dict(row.schema_hints_json).get("wkid") or "").strip()
                }
            )
            feature_count = max(
                [int(_safe_dict(row.schema_hints_json).get("feature_count") or 0) for row in arcgis_rows] or [0]
            )
            attribute_fields = sorted({item["name"] for item in normalized_hints if item.get("name")})
            arcgis_summary = {
                "geometry_types": geometry_types,
                "wkids": wkids,
                "feature_count": feature_count,
                "attribute_fields": attribute_fields,
            }
        return {
            "record_count": queryset.count(),
            "sample_records": sample_records,
            "field_hints": normalized_hints,
            "warnings": warnings,
            "adapter_kinds": sorted({kind for kind in adapter_kinds if kind}),
            "source_formats": sorted({fmt for fmt in source_formats if fmt}),
            "arcgis_summary": arcgis_summary,
        }

    @transaction.atomic
    def backfill_for_run(self, *, source_connector: models.SourceConnector, run: models.OrchestrationRun) -> int:
        rows = list(
            models.IngestParsedRecord.objects.filter(source_connector=source_connector, orchestration_run=run).order_by("created_at", "id")
        )
        created = 0
        for row in rows:
            created += len(self.adapt_parsed_record(source_connector=source_connector, parsed_row=row))
        return created
