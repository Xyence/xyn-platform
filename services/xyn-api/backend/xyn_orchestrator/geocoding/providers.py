from __future__ import annotations

from typing import Any

import requests

from .interfaces import (
    GeocodeProvider,
    GeocodeProviderCandidate,
    GeocodeProviderRequest,
    GeocodeProviderResponse,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class ArcGisGeocoderProvider(GeocodeProvider):
    kind = "arcgis_rest_geocoder"
    name = "arcgis_rest_geocoder"
    version = "1.0"

    def geocode(self, *, request: GeocodeProviderRequest) -> GeocodeProviderResponse:
        config = _safe_dict(request.provider_config)
        endpoint = str(config.get("url") or "").strip()
        if not endpoint:
            return GeocodeProviderResponse(
                status="provider_not_configured",
                error_category="provider_not_configured",
                error_message="geocoder URL is required",
            )
        timeout_seconds = int(config.get("timeout_seconds") or 15)
        default_params = _safe_dict(config.get("params"))
        single_line_field = str(config.get("single_line_field") or "SingleLine").strip() or "SingleLine"
        params: dict[str, Any] = {
            **default_params,
            single_line_field: request.normalized_address or request.raw_address,
            "f": "json",
        }
        request_context = {
            "endpoint": endpoint,
            "params": {str(k): str(v) for k, v in params.items()},
            "timeout_seconds": timeout_seconds,
        }
        try:
            response = requests.get(endpoint, params=params, timeout=(5, max(5, timeout_seconds)))
            status_code = int(response.status_code)
            payload = _safe_dict(response.json())
        except requests.RequestException as exc:
            return GeocodeProviderResponse(
                status="provider_error",
                request_context=request_context,
                error_category="provider_error",
                error_message=str(exc),
            )
        except ValueError:
            return GeocodeProviderResponse(
                status="shape_error",
                request_context=request_context,
                error_category="shape_error",
                error_message="geocoder response is not valid JSON",
            )

        response_context = {"status_code": status_code, "payload": payload}
        error_payload = _safe_dict(payload.get("error"))
        if error_payload:
            return GeocodeProviderResponse(
                status="provider_error",
                request_context=request_context,
                response_context=response_context,
                error_category="provider_error",
                error_message=str(error_payload.get("message") or "arcgis geocoder error"),
            )

        candidate_rows = payload.get("candidates")
        if not isinstance(candidate_rows, list):
            return GeocodeProviderResponse(
                status="shape_error",
                request_context=request_context,
                response_context=response_context,
                error_category="shape_error",
                error_message="arcgis geocoder payload missing candidates list",
            )

        global_spatial_ref = _safe_dict(payload.get("spatialReference"))
        parsed: list[GeocodeProviderCandidate] = []
        for index, candidate in enumerate(candidate_rows, start=1):
            row = _safe_dict(candidate)
            location = _safe_dict(row.get("location"))
            score_raw = row.get("score")
            confidence_raw = row.get("confidence")
            score = float(score_raw) if isinstance(score_raw, (int, float)) else None
            confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
            parsed.append(
                GeocodeProviderCandidate(
                    rank=index,
                    score=score,
                    confidence=confidence,
                    label=str(row.get("address") or row.get("match_addr") or "").strip(),
                    matched_address=str(row.get("address") or row.get("match_addr") or "").strip(),
                    location=location,
                    spatial_reference=global_spatial_ref,
                    attributes=_safe_dict(row.get("attributes")),
                )
            )

        if not parsed:
            return GeocodeProviderResponse(
                status="no_candidates",
                candidates=tuple(),
                request_context=request_context,
                response_context=response_context,
            )
        return GeocodeProviderResponse(
            status="success",
            candidates=tuple(parsed),
            request_context=request_context,
            response_context=response_context,
        )

