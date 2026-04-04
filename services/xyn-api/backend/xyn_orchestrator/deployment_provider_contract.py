from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Protocol


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

    def default_dns_provider(self) -> str:
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

    def default_dns_provider(self) -> str:
        return "route53"


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
    }


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
