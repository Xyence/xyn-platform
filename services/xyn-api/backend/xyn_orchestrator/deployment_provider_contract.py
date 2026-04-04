from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Protocol


@dataclass(frozen=True)
class DeploymentProviderContract:
    provider_key: str
    title: str
    implementation_kind: str
    execution_path: str
    artifact_extension_expected: bool
    notes: List[str]


_PROVIDER_REGISTRY: Dict[str, DeploymentProviderContract] = {}
_PROVIDER_IMPLEMENTATIONS: Dict[str, "DeploymentProviderImplementation"] = {}


class DeploymentProviderImplementation(Protocol):
    provider_key: str

    def describe(self) -> Dict[str, object]:
        ...

    def describe_deployment_target_contract(self) -> Dict[str, object]:
        ...

    def default_dns_provider(self) -> str:
        ...

    def normalize_dns_provider_config(self, *, dns_provider: str, config: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def validate_dns_provider_config(self, *, dns_provider: str, config: Dict[str, Any]) -> List[str]:
        ...

    def build_release_target_preparation_metadata(
        self,
        *,
        dns_provider: str,
        dns_config: Dict[str, Any],
        runtime_config: Dict[str, Any],
        tls_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...

    def evaluate_dns_deprovision_readiness(self, *, dns_provider: str, dns_config: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def resolve_dns_deprovision_orchestration(
        self, *, dns_provider: str, fqdn: str, release_target_id: str
    ) -> Dict[str, Any]:
        ...

    def derive_dns_deprovision_preparation_actions(
        self, *, dns_provider: str, fqdn: str, release_target_id: str
    ) -> List[Dict[str, Any]]:
        ...

    def derive_dns_deploy_preparation_actions(
        self, *, dns_provider: str, fqdn: str, target_instance_id: str
    ) -> List[Dict[str, Any]]:
        ...

    def evaluate_dns_deploy_preparation_readiness(
        self,
        *,
        dns_provider: str,
        fqdn: str,
        target_instance_id: str,
        dns_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...

    def evaluate_execution_preflight_readiness(
        self,
        *,
        operation: str,
        runtime_config: Dict[str, Any],
        target_instance_id: str,
        aws_region: str,
        remote_root: str,
    ) -> Dict[str, Any]:
        ...


@dataclass(frozen=True)
class LegacyAwsSsmRoute53ProviderStub:
    provider_key: str = "aws_ssm_route53"

    def describe(self) -> Dict[str, object]:
        return {
            "provider_key": self.provider_key,
            "resolution_mode": "seam_stub",
            "execution_kind": "legacy_core",
            "implementation_target": "xyn_orchestrator.deployment_provider_contract",
            "selection_scope": ["planning", "analysis", "metadata_summary"],
            "notes": [
                "Current execution remains core-coded while seam migration is in progress.",
                "New provider-specific behavior should be implemented through seam-registered modules.",
            ],
        }

    def describe_deployment_target_contract(self) -> Dict[str, object]:
        return {
            "seam_source": "deployment_provider_contract",
            "provider_key": self.provider_key,
            "target_profile_kind": "sibling_runtime",
            "runtime_target_kind": "ec2_instance",
            "provider_identity": {
                "cloud": "aws",
                "transport": "ssm",
                "dns_provider_default": "route53",
            },
            "capability_categories": [
                "prepare_runtime_target",
                "prepare_dns_target",
                "execution_preflight",
            ],
            "required_configuration": [
                "release_target.target_instance_id",
                "target_instance.aws_region",
                "release_target.runtime.transport",
                "release_target.runtime.remote_root",
            ],
            "dns_exposure_expectations": {
                "supported_provider_kinds": ["route53"],
                "required_inputs": [
                    "release_target.dns_provider.hosted_zone_id",
                    "release_target.dns_provider.credentials_ref.context_pack_id",
                ],
            },
            "execution_support": {
                "deploy_execution_in_scope": False,
                "preflight_only": True,
                "notes": [
                    "Execution/apply remains outside this seam-backed contract slice.",
                ],
            },
            "provider_module_contract": {
                "module_id": "deploy-aws-ec2-sibling",
                "module_manifest_ref": "backend/registry/modules/deploy-aws-ec2-sibling.json",
                "capabilities_expected": [
                    "runtime.sibling.ec2.preparation",
                    "runtime.sibling.ec2.provision",
                    "runtime.compose.apply_remote",
                    "dns.route53.records",
                ],
                "deployment_target_defaults": {
                    "instance_type": "t3.small",
                    "hostname_pattern": "{app}.{zone}",
                },
            },
        }

    def default_dns_provider(self) -> str:
        return "route53"

    def normalize_dns_provider_config(self, *, dns_provider: str, config: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(config or {})
        provider = str(dns_provider or "").strip().lower()
        if provider == "route53" and normalized and not str(normalized.get("kind") or "").strip():
            normalized["kind"] = "route53"
        return normalized

    def validate_dns_provider_config(self, *, dns_provider: str, config: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        provider = str(dns_provider or "").strip().lower()
        kind = str((config or {}).get("kind") or "").strip().lower()
        if kind and kind != "route53":
            errors.append("dns_provider.kind: only route53 is supported by the aws_ssm_route53 provider seam")
            return errors
        if provider and provider != "route53":
            errors.append(f"dns.provider: provider '{provider}' is not supported by aws_ssm_route53")
            return errors
        hosted_zone_id = str((config or {}).get("hosted_zone_id") or "").strip()
        credentials_ref = (config or {}).get("credentials_ref") if isinstance((config or {}).get("credentials_ref"), dict) else {}
        context_pack_id = str(credentials_ref.get("context_pack_id") or "").strip()
        if hosted_zone_id and not context_pack_id:
            errors.append("dns_provider.credentials_ref.context_pack_id: required when dns_provider.hosted_zone_id is set")
        if context_pack_id and not hosted_zone_id:
            errors.append("dns_provider.hosted_zone_id: required when dns_provider.credentials_ref.context_pack_id is set")
        return errors

    def build_release_target_preparation_metadata(
        self,
        *,
        dns_provider: str,
        dns_config: Dict[str, Any],
        runtime_config: Dict[str, Any],
        tls_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        provider = str(dns_provider or "").strip().lower() or "route53"
        hosted_zone_id = str((dns_config or {}).get("hosted_zone_id") or "").strip()
        credentials_ref = (dns_config or {}).get("credentials_ref") if isinstance((dns_config or {}).get("credentials_ref"), dict) else {}
        context_pack_id = str(credentials_ref.get("context_pack_id") or "").strip()
        runtime_transport = str((runtime_config or {}).get("transport") or "").strip().lower()
        tls_mode = str((tls_config or {}).get("mode") or "").strip().lower()
        missing_inputs: List[str] = []
        if provider == "route53":
            if not hosted_zone_id:
                missing_inputs.append("dns_provider.hosted_zone_id")
            if not context_pack_id:
                missing_inputs.append("dns_provider.credentials_ref.context_pack_id")
        return {
            "provider_key": self.provider_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": provider,
            "runtime_transport": runtime_transport,
            "tls_mode": tls_mode,
            "supports_dns_deprovision_delete": provider == "route53",
            "required_inputs": [
                "dns_provider.hosted_zone_id",
                "dns_provider.credentials_ref.context_pack_id",
            ] if provider == "route53" else [],
            "missing_inputs": missing_inputs,
        }

    def evaluate_dns_deprovision_readiness(self, *, dns_provider: str, dns_config: Dict[str, Any]) -> Dict[str, Any]:
        provider = str(dns_provider or "").strip().lower() or "route53"
        can_delete = provider == "route53"
        blocked_reason = ""
        if not can_delete:
            blocked_reason = f"dns provider '{provider}' is not supported for deprovision delete"
        return {
            "provider_key": self.provider_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": provider,
            "can_delete_dns_record": can_delete,
            "blocked_reason": blocked_reason,
        }

    def resolve_dns_deprovision_orchestration(
        self, *, dns_provider: str, fqdn: str, release_target_id: str
    ) -> Dict[str, Any]:
        provider = str(dns_provider or "").strip().lower() or "route53"
        can_orchestrate = provider == "route53"
        if not can_orchestrate:
            return {
                "provider_key": self.provider_key,
                "seam_source": "deployment_provider_contract",
                "dns_provider": provider,
                "can_orchestrate": False,
                "blocked_reason": f"dns provider '{provider}' has no deprovision orchestration mapping",
                "step_capability": "",
                "step_id": "",
                "step_title": "",
            }
        return {
            "provider_key": self.provider_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": provider,
            "can_orchestrate": True,
            "blocked_reason": "",
            "step_capability": "dns.route53.delete_record",
            "step_id": f"dns.delete_record.route53.{release_target_id}",
            "step_title": f"Delete Route53 record for {fqdn}",
        }

    def derive_dns_deprovision_preparation_actions(
        self, *, dns_provider: str, fqdn: str, release_target_id: str
    ) -> List[Dict[str, Any]]:
        orchestration = self.resolve_dns_deprovision_orchestration(
            dns_provider=dns_provider,
            fqdn=fqdn,
            release_target_id=release_target_id,
        )
        if not bool(orchestration.get("can_orchestrate")):
            return []
        return [
            {
                "provider_key": self.provider_key,
                "action_key": "dns_delete_record",
                "required": True,
                "capability": str(orchestration.get("step_capability") or "dns.route53.delete_record"),
                "step_id": str(orchestration.get("step_id") or ""),
                "title": str(orchestration.get("step_title") or ""),
                "reason": "provider_mapped_dns_record_deprovision",
            }
        ]

    def derive_dns_deploy_preparation_actions(
        self, *, dns_provider: str, fqdn: str, target_instance_id: str
    ) -> List[Dict[str, Any]]:
        provider = str(dns_provider or "").strip().lower() or "route53"
        if provider != "route53":
            return []
        return [
            {
                "provider_key": self.provider_key,
                "action_key": "dns_ensure_record",
                "required": True,
                "capability": "dns.route53.records",
                "step_id": "dns.ensure_record.route53",
                "title": "Ensure Route53 DNS record",
                "reason": "provider_mapped_dns_record_deploy_preparation",
                "fqdn": str(fqdn or "").strip(),
                "target_instance_id": str(target_instance_id or "").strip(),
            }
        ]

    def evaluate_dns_deploy_preparation_readiness(
        self,
        *,
        dns_provider: str,
        fqdn: str,
        target_instance_id: str,
        dns_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        provider = str(dns_provider or "").strip().lower() or "route53"
        fqdn_value = str(fqdn or "").strip()
        target_id = str(target_instance_id or "").strip()
        hosted_zone_id = str((dns_config or {}).get("hosted_zone_id") or "").strip()
        credentials_ref = (dns_config or {}).get("credentials_ref") if isinstance((dns_config or {}).get("credentials_ref"), dict) else {}
        context_pack_id = str(credentials_ref.get("context_pack_id") or "").strip()
        missing_inputs: List[str] = []
        blocked_reason = ""
        if provider != "route53":
            blocked_reason = f"dns provider '{provider}' is not supported for deploy preparation"
        if not fqdn_value:
            missing_inputs.append("release_target.fqdn")
        if not target_id:
            missing_inputs.append("release_target.target_instance_id")
        if provider == "route53":
            if not hosted_zone_id:
                missing_inputs.append("release_target.dns_provider.hosted_zone_id")
            if not context_pack_id:
                missing_inputs.append("release_target.dns_provider.credentials_ref.context_pack_id")
        can_prepare = not blocked_reason and not missing_inputs
        return {
            "provider_key": self.provider_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": provider,
            "can_prepare": bool(can_prepare),
            "blocked_reason": blocked_reason,
            "missing_inputs": missing_inputs,
        }

    def evaluate_execution_preflight_readiness(
        self,
        *,
        operation: str,
        runtime_config: Dict[str, Any],
        target_instance_id: str,
        aws_region: str,
        remote_root: str,
    ) -> Dict[str, Any]:
        op = str(operation or "").strip().lower()
        runtime = dict(runtime_config or {})
        transport = str(runtime.get("transport") or "").strip().lower()
        target_id = str(target_instance_id or "").strip()
        region = str(aws_region or "").strip()
        root = str(remote_root or "").strip()
        missing_inputs: List[str] = []
        blocked_reason = ""
        if transport and transport != "ssm":
            blocked_reason = f"runtime transport '{transport}' is not supported by aws_ssm_route53 execution preflight"
        if not target_id:
            missing_inputs.append("target_instance_id")
        if not region:
            missing_inputs.append("target_instance.aws_region")
        if not root:
            missing_inputs.append("runtime.remote_root")
        can_probe_runtime_marker = not blocked_reason and not missing_inputs and op in {"check_drift", "drift_check"}
        can_prepare_runtime_root = not blocked_reason and not missing_inputs and op in {
            "prepare_runtime_root",
            "runtime_prepare_root",
            "prepare_root",
        }
        return {
            "provider_key": self.provider_key,
            "seam_source": "deployment_provider_contract",
            "operation": op,
            "runtime_transport": transport or "ssm",
            "can_probe_runtime_marker": bool(can_probe_runtime_marker),
            "can_prepare_runtime_root": bool(can_prepare_runtime_root),
            "blocked_reason": blocked_reason,
            "missing_inputs": missing_inputs,
        }


def register_deployment_provider_contract(contract: DeploymentProviderContract) -> None:
    token = str(contract.provider_key or "").strip().lower()
    if not token:
        raise ValueError("deployment provider contract key is required")
    _PROVIDER_REGISTRY[token] = contract


def register_deployment_provider_implementation(implementation: DeploymentProviderImplementation) -> None:
    token = str(getattr(implementation, "provider_key", "") or "").strip().lower()
    if not token:
        raise ValueError("deployment provider implementation key is required")
    _PROVIDER_IMPLEMENTATIONS[token] = implementation


def list_deployment_provider_contracts() -> List[DeploymentProviderContract]:
    return [
        _PROVIDER_REGISTRY[key]
        for key in sorted(_PROVIDER_REGISTRY.keys())
    ]


def resolve_deployment_provider_contract(provider_key: str) -> DeploymentProviderContract | None:
    token = str(provider_key or "").strip().lower()
    if not token:
        return None
    return _PROVIDER_REGISTRY.get(token)


def resolve_deployment_provider_implementation(provider_key: str) -> DeploymentProviderImplementation | None:
    token = str(provider_key or "").strip().lower()
    if not token:
        return None
    return _PROVIDER_IMPLEMENTATIONS.get(token)


def resolve_deployment_provider_for_request(request_text: str, *, capability_domain: str = "deployment") -> Dict[str, object]:
    ensure_default_deployment_provider_contracts()
    domain = str(capability_domain or "").strip().lower()
    if domain and domain != "deployment":
        return {"resolved": False, "reason": "unsupported_domain"}
    tokens = {str(token).strip().lower() for token in re.findall(r"[A-Za-z0-9_]+", str(request_text or "")) if str(token).strip()}
    aws_like = bool(tokens.intersection({"aws", "ec2", "eks", "route53"}))
    selected_key = "aws_ssm_route53" if aws_like or domain == "deployment" else ""
    if not selected_key:
        return {"resolved": False, "reason": "no_provider_candidate"}
    contract = resolve_deployment_provider_contract(selected_key)
    implementation = resolve_deployment_provider_implementation(selected_key)
    return {
        "resolved": bool(contract and implementation),
        "selected_provider_key": selected_key,
        "resolution_reason": "matched_provider_tokens" if aws_like else "deployment_default_legacy_provider",
        "contract": {
            "provider_key": contract.provider_key if contract else selected_key,
            "title": contract.title if contract else "",
            "implementation_kind": contract.implementation_kind if contract else "",
            "execution_path": contract.execution_path if contract else "",
            "artifact_extension_expected": bool(contract.artifact_extension_expected) if contract else True,
        },
        "implementation": implementation.describe() if implementation else {},
        "deployment_target_contract": implementation.describe_deployment_target_contract() if implementation else {},
    }


def resolve_deployment_target_contract(*, selected_provider_key: str = "") -> Dict[str, object]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    if implementation is None:
        return {
            "seam_source": "deployment_provider_contract",
            "provider_key": selected_key,
            "target_profile_kind": "unknown",
            "runtime_target_kind": "",
            "provider_identity": {},
            "capability_categories": [],
            "required_configuration": [],
            "dns_exposure_expectations": {},
            "execution_support": {
                "deploy_execution_in_scope": False,
                "preflight_only": True,
                "notes": ["deployment provider implementation not found"],
            },
            "provider_module_contract": {},
        }
    return implementation.describe_deployment_target_contract()


def resolve_deployment_dns_profile(*, requested_provider: str = "") -> Dict[str, object]:
    ensure_default_deployment_provider_contracts()
    requested = str(requested_provider or "").strip().lower()
    selected_key = "aws_ssm_route53"
    if requested in {"route53", "aws_ssm_route53", "aws"}:
        selected_key = "aws_ssm_route53"
    contract = resolve_deployment_provider_contract(selected_key)
    implementation = resolve_deployment_provider_implementation(selected_key)
    default_provider = implementation.default_dns_provider() if implementation is not None else "route53"
    return {
        "resolved": bool(contract and implementation),
        "selected_provider_key": selected_key,
        "requested_provider": requested,
        "default_dns_provider": str(default_provider or "route53"),
        "contract": {
            "provider_key": contract.provider_key if contract else selected_key,
            "execution_path": contract.execution_path if contract else "",
            "implementation_kind": contract.implementation_kind if contract else "",
        },
    }


def normalize_deployment_dns_provider_config(
    *,
    dns_provider: str = "",
    config: Dict[str, Any] | None = None,
    selected_provider_key: str = "",
) -> Dict[str, Any]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    if implementation is None:
        return dict(config or {})
    return implementation.normalize_dns_provider_config(
        dns_provider=str(dns_provider or "").strip().lower(),
        config=dict(config or {}),
    )


def validate_deployment_dns_provider_config(
    *,
    dns_provider: str = "",
    config: Dict[str, Any] | None = None,
    selected_provider_key: str = "",
) -> List[str]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    if implementation is None:
        return []
    return implementation.validate_dns_provider_config(
        dns_provider=str(dns_provider or "").strip().lower(),
        config=dict(config or {}),
    )


def build_deployment_release_target_preparation_metadata(
    *,
    dns_provider: str = "",
    dns_config: Dict[str, Any] | None = None,
    runtime_config: Dict[str, Any] | None = None,
    tls_config: Dict[str, Any] | None = None,
    selected_provider_key: str = "",
) -> Dict[str, Any]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    if implementation is None:
        return {
            "provider_key": selected_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": str(dns_provider or "").strip().lower(),
            "required_inputs": [],
            "missing_inputs": [],
        }
    return implementation.build_release_target_preparation_metadata(
        dns_provider=str(dns_provider or "").strip().lower(),
        dns_config=dict(dns_config or {}),
        runtime_config=dict(runtime_config or {}),
        tls_config=dict(tls_config or {}),
    )


def evaluate_deployment_dns_deprovision_readiness(
    *,
    dns_provider: str = "",
    dns_config: Dict[str, Any] | None = None,
    selected_provider_key: str = "",
) -> Dict[str, Any]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    provider = str(dns_provider or "").strip().lower()
    if implementation is None:
        return {
            "provider_key": selected_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": provider,
            "can_delete_dns_record": False,
            "blocked_reason": "deployment provider implementation not found",
        }
    return implementation.evaluate_dns_deprovision_readiness(
        dns_provider=provider,
        dns_config=dict(dns_config or {}),
    )


def resolve_deployment_dns_deprovision_orchestration(
    *,
    dns_provider: str = "",
    fqdn: str = "",
    release_target_id: str = "",
    selected_provider_key: str = "",
) -> Dict[str, Any]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    provider = str(dns_provider or "").strip().lower()
    if implementation is None:
        return {
            "provider_key": selected_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": provider,
            "can_orchestrate": False,
            "blocked_reason": "deployment provider implementation not found",
            "step_capability": "",
            "step_id": "",
            "step_title": "",
        }
    return implementation.resolve_dns_deprovision_orchestration(
        dns_provider=provider,
        fqdn=str(fqdn or "").strip(),
        release_target_id=str(release_target_id or "").strip(),
    )


def derive_deployment_dns_deprovision_preparation_actions(
    *,
    dns_provider: str = "",
    fqdn: str = "",
    release_target_id: str = "",
    selected_provider_key: str = "",
) -> List[Dict[str, Any]]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    provider = str(dns_provider or "").strip().lower()
    if implementation is None:
        return []
    return implementation.derive_dns_deprovision_preparation_actions(
        dns_provider=provider,
        fqdn=str(fqdn or "").strip(),
        release_target_id=str(release_target_id or "").strip(),
    )


def derive_deployment_dns_deploy_preparation_actions(
    *,
    dns_provider: str = "",
    fqdn: str = "",
    target_instance_id: str = "",
    selected_provider_key: str = "",
) -> List[Dict[str, Any]]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    provider = str(dns_provider or "").strip().lower()
    if implementation is None:
        return []
    return implementation.derive_dns_deploy_preparation_actions(
        dns_provider=provider,
        fqdn=str(fqdn or "").strip(),
        target_instance_id=str(target_instance_id or "").strip(),
    )


def evaluate_deployment_dns_deploy_preparation_readiness(
    *,
    dns_provider: str = "",
    fqdn: str = "",
    target_instance_id: str = "",
    dns_config: Dict[str, Any] | None = None,
    selected_provider_key: str = "",
) -> Dict[str, Any]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    provider = str(dns_provider or "").strip().lower()
    if implementation is None:
        return {
            "provider_key": selected_key,
            "seam_source": "deployment_provider_contract",
            "dns_provider": provider,
            "can_prepare": False,
            "blocked_reason": "deployment provider implementation not found",
            "missing_inputs": [],
        }
    return implementation.evaluate_dns_deploy_preparation_readiness(
        dns_provider=provider,
        fqdn=str(fqdn or "").strip(),
        target_instance_id=str(target_instance_id or "").strip(),
        dns_config=dict(dns_config or {}),
    )


def evaluate_deployment_execution_preflight_readiness(
    *,
    operation: str = "",
    runtime_config: Dict[str, Any] | None = None,
    target_instance_id: str = "",
    aws_region: str = "",
    remote_root: str = "",
    selected_provider_key: str = "",
) -> Dict[str, Any]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    implementation = resolve_deployment_provider_implementation(selected_key)
    if implementation is None:
        return {
            "provider_key": selected_key,
            "seam_source": "deployment_provider_contract",
            "operation": str(operation or "").strip().lower(),
            "runtime_transport": str((runtime_config or {}).get("transport") or "").strip().lower(),
            "can_probe_runtime_marker": False,
            "can_prepare_runtime_root": False,
            "blocked_reason": "deployment provider implementation not found",
            "missing_inputs": [],
        }
    return implementation.evaluate_execution_preflight_readiness(
        operation=str(operation or "").strip().lower(),
        runtime_config=dict(runtime_config or {}),
        target_instance_id=str(target_instance_id or "").strip(),
        aws_region=str(aws_region or "").strip(),
        remote_root=str(remote_root or "").strip(),
    )


def _load_provider_module_manifest(module_manifest_ref: str) -> Dict[str, Any]:
    reference = str(module_manifest_ref or "").strip()
    if not reference:
        return {}
    normalized = reference.replace("\\", "/")
    if normalized.startswith("backend/"):
        normalized = normalized[len("backend/"):]
    backend_root = Path(__file__).resolve().parents[1]
    manifest_path = (backend_root / normalized).resolve()
    try:
        if not manifest_path.exists() or not manifest_path.is_file():
            return {}
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _discover_aws_account_context(*, enabled: bool) -> Dict[str, Any]:
    if not enabled:
        return {"attempted": False, "discovered": False, "source": "", "account_id": "", "warning": ""}
    disabled = str(os.environ.get("XYN_DISABLE_AWS_ACCOUNT_DISCOVERY") or "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return {
            "attempted": False,
            "discovered": False,
            "source": "env_guardrail",
            "account_id": "",
            "warning": "AWS account discovery disabled by XYN_DISABLE_AWS_ACCOUNT_DISCOVERY.",
        }
    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--output", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=6,
        )
    except Exception as exc:
        return {
            "attempted": True,
            "discovered": False,
            "source": "aws_cli",
            "account_id": "",
            "warning": f"AWS CLI discovery failed: {exc}",
        }
    if result.returncode != 0:
        warning = str(result.stderr or result.stdout or "").strip() or "aws sts get-caller-identity failed"
        return {
            "attempted": True,
            "discovered": False,
            "source": "aws_cli",
            "account_id": "",
            "warning": warning,
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "attempted": True,
            "discovered": False,
            "source": "aws_cli",
            "account_id": "",
            "warning": "aws sts get-caller-identity returned non-JSON output",
        }
    account_id = str(payload.get("Account") or "").strip()
    return {
        "attempted": True,
        "discovered": bool(account_id),
        "source": "aws_cli_sts",
        "account_id": account_id,
        "warning": "" if account_id else "AWS account id unavailable from aws sts get-caller-identity",
    }


def _lookup_input_value(context: Dict[str, Any], dotted_key: str) -> tuple[bool, Any]:
    current: Any = context
    for token in str(dotted_key or "").split("."):
        if not isinstance(current, dict) or token not in current:
            return False, None
        current = current[token]
    if current is None:
        return False, None
    if isinstance(current, str) and not current.strip():
        return False, current
    if isinstance(current, (list, dict)) and not current:
        return False, current
    return True, current


def build_non_destructive_deployment_plan(
    *,
    selected_provider_key: str = "",
    release_target_id: str = "",
    blueprint_ref: str = "",
    solution_name: str = "",
    target_instance_id: str = "",
    aws_region: str = "",
    runtime_config: Dict[str, Any] | None = None,
    dns_provider: str = "",
    dns_config: Dict[str, Any] | None = None,
    fqdn: str = "",
    instance_type: str = "",
    discover_environment: bool = False,
) -> Dict[str, Any]:
    ensure_default_deployment_provider_contracts()
    selected_key = str(selected_provider_key or "").strip().lower() or "aws_ssm_route53"
    target_contract = resolve_deployment_target_contract(selected_provider_key=selected_key)
    module_contract = target_contract.get("provider_module_contract") if isinstance(target_contract, dict) else {}
    module_contract = module_contract if isinstance(module_contract, dict) else {}
    module_manifest_ref = str(module_contract.get("module_manifest_ref") or "").strip()
    module_manifest = _load_provider_module_manifest(module_manifest_ref)
    module_interfaces = module_manifest.get("module", {}).get("interfaces", {}) if isinstance(module_manifest, dict) else {}
    module_config_interface = module_interfaces.get("config") if isinstance(module_interfaces, dict) else {}
    module_config_interface = module_config_interface if isinstance(module_config_interface, dict) else {}
    module_operations = module_interfaces.get("operations") if isinstance(module_interfaces, dict) else {}
    module_operations = module_operations if isinstance(module_operations, dict) else {}
    capability_categories = target_contract.get("capability_categories") if isinstance(target_contract, dict) else []
    declared_capabilities = {str(item).strip() for item in capability_categories or [] if str(item).strip()}
    provider_identity = target_contract.get("provider_identity") if isinstance(target_contract, dict) else {}
    provider_identity = provider_identity if isinstance(provider_identity, dict) else {}
    provider_cloud = str(provider_identity.get("cloud") or "").strip().lower()
    provider_dns_default = str(provider_identity.get("dns_provider_default") or "").strip().lower() or "route53"
    effective_dns_provider = str(dns_provider or "").strip().lower() or provider_dns_default
    effective_runtime = dict(runtime_config or {})
    effective_dns_config = dict(dns_config or {})
    effective_instance_type = str(instance_type or "").strip() or str(
        ((module_contract.get("deployment_target_defaults") or {}).get("instance_type") if isinstance(module_contract, dict) else "")
        or ""
    ).strip()
    effective_fqdn = str(fqdn or "").strip()
    aws_context = _discover_aws_account_context(enabled=bool(discover_environment and provider_cloud == "aws"))

    input_context: Dict[str, Any] = {
        "release_target": {
            "target_instance_id": str(target_instance_id or "").strip(),
            "fqdn": effective_fqdn,
            "runtime": {
                "transport": str((effective_runtime or {}).get("transport") or "").strip().lower(),
                "remote_root": str((effective_runtime or {}).get("remote_root") or "").strip(),
            },
            "dns_provider": effective_dns_config,
        },
        "target_instance": {
            "aws_region": str(aws_region or "").strip(),
            "aws_account_id": str(aws_context.get("account_id") or "").strip(),
        },
        "requested": {
            "instance_type": effective_instance_type,
            "hostname": effective_fqdn,
            "solution_name": str(solution_name or "").strip(),
        },
    }

    required_inputs: List[Dict[str, Any]] = []
    missing_inputs: List[str] = []
    contract_required = target_contract.get("required_configuration") if isinstance(target_contract, dict) else []
    dns_expectations = target_contract.get("dns_exposure_expectations") if isinstance(target_contract, dict) else {}
    dns_required = dns_expectations.get("required_inputs") if isinstance(dns_expectations, dict) else []
    all_required_keys: List[str] = []
    all_required_keys.extend([str(key).strip() for key in contract_required or [] if str(key).strip()])
    all_required_keys.extend([str(key).strip() for key in dns_required or [] if str(key).strip()])
    seen_required: set[str] = set()
    for required_key in all_required_keys:
        if required_key in seen_required:
            continue
        seen_required.add(required_key)
        present, value = _lookup_input_value(input_context, required_key)
        if not present:
            missing_inputs.append(required_key)
        required_inputs.append(
            {
                "key": required_key,
                "provided": bool(present),
                "value": value if present else None,
            }
        )

    dns_readiness = evaluate_deployment_dns_deploy_preparation_readiness(
        dns_provider=effective_dns_provider,
        fqdn=effective_fqdn,
        target_instance_id=str(target_instance_id or "").strip(),
        dns_config=effective_dns_config,
        selected_provider_key=selected_key,
    )
    dns_actions = derive_deployment_dns_deploy_preparation_actions(
        dns_provider=effective_dns_provider,
        fqdn=effective_fqdn,
        target_instance_id=str(target_instance_id or "").strip(),
        selected_provider_key=selected_key,
    )
    execution_preflight = evaluate_deployment_execution_preflight_readiness(
        operation="check_drift",
        runtime_config=effective_runtime,
        target_instance_id=str(target_instance_id or "").strip(),
        aws_region=str(aws_region or "").strip(),
        remote_root=str((effective_runtime or {}).get("remote_root") or "").strip(),
        selected_provider_key=selected_key,
    )

    steps: List[Dict[str, Any]] = []
    contract_ready = bool(module_contract)
    steps.append(
        {
            "id": "resolve.provider_module_contract",
            "title": "Resolve provider module contract",
            "capability_category": "module_contract_resolution",
            "status": "ready" if contract_ready else "blocked",
            "blocked_reason": "" if contract_ready else "provider module contract is missing",
            "notes": "Non-destructive planning uses the seam + module contract as the source of truth.",
        }
    )

    runtime_missing = [
        key
        for key in [
            "release_target.target_instance_id",
            "target_instance.aws_region",
            "release_target.runtime.transport",
            "release_target.runtime.remote_root",
        ]
        if key in missing_inputs
    ]
    if "prepare_runtime_target" in declared_capabilities:
        steps.append(
            {
                "id": "prepare.runtime_target",
                "title": "Prepare sibling runtime target prerequisites",
                "capability_category": "prepare_runtime_target",
                "status": "ready" if not runtime_missing else "blocked",
                "blocked_reason": "" if not runtime_missing else "missing required runtime target inputs",
                "missing_inputs": runtime_missing,
                "notes": module_operations.get("prepare_runtime_target")
                or "Validate target/profile inputs without mutating infrastructure.",
            }
        )
    else:
        steps.append(
            {
                "id": "prepare.runtime_target",
                "title": "Prepare sibling runtime target prerequisites",
                "capability_category": "prepare_runtime_target",
                "status": "not_executed",
                "blocked_reason": "capability category is not declared by provider contract",
                "missing_inputs": runtime_missing,
                "notes": "",
            }
        )

    if "prepare_dns_target" in declared_capabilities:
        steps.append(
            {
                "id": "prepare.dns_target",
                "title": "Prepare DNS exposure prerequisites",
                "capability_category": "prepare_dns_target",
                "status": "ready" if bool(dns_readiness.get("can_prepare")) else "blocked",
                "blocked_reason": str(dns_readiness.get("blocked_reason") or "").strip(),
                "missing_inputs": list(dns_readiness.get("missing_inputs") or []),
                "planned_actions": dns_actions,
                "notes": module_operations.get("prepare_dns_target")
                or "Derive DNS preparation actions without applying DNS changes.",
            }
        )
    else:
        steps.append(
            {
                "id": "prepare.dns_target",
                "title": "Prepare DNS exposure prerequisites",
                "capability_category": "prepare_dns_target",
                "status": "not_executed",
                "blocked_reason": "capability category is not declared by provider contract",
                "missing_inputs": list(dns_readiness.get("missing_inputs") or []),
                "planned_actions": dns_actions,
                "notes": "",
            }
        )

    preflight_missing = list(execution_preflight.get("missing_inputs") or [])
    preflight_blocked_reason = str(execution_preflight.get("blocked_reason") or "").strip()
    if "execution_preflight" in declared_capabilities:
        steps.append(
            {
                "id": "prepare.execution_preflight",
                "title": "Evaluate execution-adjacent preflight readiness",
                "capability_category": "execution_preflight",
                "status": "ready" if (not preflight_missing and not preflight_blocked_reason) else "blocked",
                "blocked_reason": preflight_blocked_reason,
                "missing_inputs": preflight_missing,
                "preflight": execution_preflight,
                "notes": module_operations.get("execution_preflight")
                or "Run non-destructive preflight checks only.",
            }
        )
    else:
        steps.append(
            {
                "id": "prepare.execution_preflight",
                "title": "Evaluate execution-adjacent preflight readiness",
                "capability_category": "execution_preflight",
                "status": "not_executed",
                "blocked_reason": "capability category is not declared by provider contract",
                "missing_inputs": preflight_missing,
                "preflight": execution_preflight,
                "notes": "",
            }
        )

    warnings: List[str] = []
    aws_warning = str(aws_context.get("warning") or "").strip()
    if aws_warning:
        warnings.append(aws_warning)
    warnings.append("This is a non-destructive deployment plan only; no AWS, Route53, or remote runtime mutation was performed.")

    actionable_steps = [step for step in steps if str(step.get("status") or "") != "not_executed"]
    execution_ready = bool(actionable_steps) and all(str(step.get("status") or "") == "ready" for step in actionable_steps)

    discovered_inputs: List[Dict[str, Any]] = []
    if str(aws_context.get("account_id") or "").strip():
        discovered_inputs.append(
            {
                "key": "target_instance.aws_account_id",
                "value": str(aws_context.get("account_id") or "").strip(),
                "source": str(aws_context.get("source") or "aws_cli_sts"),
            }
        )

    return {
        "schema_version": "xyn.deployment_plan.v1",
        "planning_mode": "non_destructive",
        "operation": "sibling_runtime_deployment_plan",
        "release_target_id": str(release_target_id or "").strip(),
        "blueprint_ref": str(blueprint_ref or "").strip(),
        "solution_name": str(solution_name or "").strip(),
        "provider_key": selected_key,
        "target_profile_kind": str(target_contract.get("target_profile_kind") or "").strip(),
        "runtime_target_kind": str(target_contract.get("runtime_target_kind") or "").strip(),
        "provider_contract": {
            "deployment_target_contract": target_contract,
            "provider_module_contract": module_contract,
            "module_manifest_ref": module_manifest_ref,
            "module_config_interface": module_config_interface,
        },
        "requested_config": {
            "instance_type": effective_instance_type,
            "hostname": effective_fqdn,
            "dns_provider": effective_dns_provider,
        },
        "required_inputs": required_inputs,
        "discovered_inputs": discovered_inputs,
        "missing_inputs": sorted(set(missing_inputs)),
        "environment_discovery": aws_context,
        "steps": steps,
        "execution_ready_in_principle": bool(execution_ready),
        "warnings": warnings,
    }


def derive_staged_execution_intent_from_deployment_plan(plan: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = dict(plan or {})
    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    blocked_steps = [step for step in steps if str((step or {}).get("status") or "").strip().lower() == "blocked"]
    ready_steps = [step for step in steps if str((step or {}).get("status") or "").strip().lower() == "ready"]
    staged_steps: List[Dict[str, Any]] = []
    required_future_inputs: List[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        missing = [str(item).strip() for item in (step.get("missing_inputs") or []) if str(item).strip()]
        required_future_inputs.extend(missing)
        staged_steps.append(
            {
                "id": str(step.get("id") or "").strip(),
                "title": str(step.get("title") or "").strip(),
                "status": str(step.get("status") or "").strip().lower() or "not_executed",
                "capability_category": str(step.get("capability_category") or "").strip(),
                "blocked_reason": str(step.get("blocked_reason") or "").strip(),
                "missing_inputs": missing,
            }
        )
    unique_future_inputs: List[str] = []
    seen: set[str] = set()
    for item in required_future_inputs:
        if item in seen:
            continue
        seen.add(item)
        unique_future_inputs.append(item)
    return {
        "schema_version": "xyn.deployment_staged_intent.v1",
        "intent_type": "staged_execution_intent",
        "mutation_performed": False,
        "provider_key": str(payload.get("provider_key") or "").strip(),
        "provider_module_contract_ref": str(
            (
                (payload.get("provider_contract") or {}).get("module_manifest_ref")
                if isinstance(payload.get("provider_contract"), dict)
                else ""
            )
            or ""
        ).strip(),
        "planning_mode": str(payload.get("planning_mode") or "").strip(),
        "operation": str(payload.get("operation") or "").strip(),
        "promotable_to_execution_in_principle": bool(payload.get("execution_ready_in_principle")),
        "blocked_steps": [str((step or {}).get("id") or "").strip() for step in blocked_steps if str((step or {}).get("id") or "").strip()],
        "ready_steps": [str((step or {}).get("id") or "").strip() for step in ready_steps if str((step or {}).get("id") or "").strip()],
        "required_future_inputs": unique_future_inputs,
        "staged_steps": staged_steps,
        "warnings": list(payload.get("warnings") or []),
    }


def ensure_default_deployment_provider_contracts() -> None:
    # Current runtime path is still core-coded. Register explicitly so future
    # provider decomposition has a first-class seam to target.
    if "aws_ssm_route53" not in _PROVIDER_REGISTRY:
        register_deployment_provider_contract(
            DeploymentProviderContract(
                provider_key="aws_ssm_route53",
                title="AWS SSM + Route53 (legacy core path)",
                implementation_kind="legacy_core",
                execution_path="xyn_orchestrator.xyn_api._intent_apply_provision_xyn_remote",
                artifact_extension_expected=True,
                notes=[
                    "Provider-specific deployment execution is currently core-coded.",
                    "New provider implementations should be introduced as artifacts/modules.",
                ],
            )
        )
    if "aws_ssm_route53" not in _PROVIDER_IMPLEMENTATIONS:
        register_deployment_provider_implementation(LegacyAwsSsmRoute53ProviderStub())
