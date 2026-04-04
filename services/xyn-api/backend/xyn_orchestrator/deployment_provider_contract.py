from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class DeploymentProviderContract:
    provider_key: str
    title: str
    implementation_kind: str
    execution_path: str
    artifact_extension_expected: bool
    notes: List[str]


_PROVIDER_REGISTRY: Dict[str, DeploymentProviderContract] = {}


def register_deployment_provider_contract(contract: DeploymentProviderContract) -> None:
    token = str(contract.provider_key or "").strip().lower()
    if not token:
        raise ValueError("deployment provider contract key is required")
    _PROVIDER_REGISTRY[token] = contract


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
