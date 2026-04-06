from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

from .deployment_provider_contract import (
    resolve_deployment_target_contract,
    ensure_default_deployment_provider_contracts,
    list_deployment_provider_contracts,
    resolve_deployment_provider_for_request,
)


PLACEMENT_POLICY_VERSION = "xyn.architecture_placement.v1"

_DEPLOYMENT_DOMAIN_TOKENS = {
    "deploy",
    "deployment",
    "provision",
    "runtime",
    "instance",
    "compose",
    "dns",
    "ingress",
    "release",
}

_PROVIDER_TOKENS = {
    "aws",
    "ec2",
    "eks",
    "route53",
    "gcp",
    "azure",
    "nutanix",
    "vmware",
}

_CORE_COUPLING_TOKENS = {
    "core",
    "orchestration",
    "orchestrator",
    "xyn_api",
    "deployments",
    "instance_drivers",
    "directly",
}

_NEUTRAL_ABSTRACTION_TOKENS = {
    "abstraction",
    "interface",
    "provider-neutral",
    "provider_neutral",
    "contract",
    "lifecycle",
}


@dataclass(frozen=True)
class PlacementDecision:
    policy_version: str
    capability_domain: str
    recommendation: str
    provider_specific: bool
    core_allowed: str
    rationale: List[str]
    next_step: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "capability_domain": self.capability_domain,
            "recommendation": self.recommendation,
            "provider_specific": self.provider_specific,
            "core_allowed": self.core_allowed,
            "rationale": list(self.rationale),
            "next_step": self.next_step,
        }


def _tokenize(text: str) -> set[str]:
    return {str(token).strip().lower() for token in re.findall(r"[A-Za-z0-9_]+", str(text or "")) if str(token).strip()}


def evaluate_architectural_placement(*, request_text: str, capability_domain: str = "auto") -> Dict[str, object]:
    ensure_default_deployment_provider_contracts()
    domain = str(capability_domain or "auto").strip().lower() or "auto"
    tokens = _tokenize(request_text)

    if domain == "auto":
        if tokens.intersection(_DEPLOYMENT_DOMAIN_TOKENS):
            domain = "deployment"
        else:
            domain = "general"

    provider_specific = bool(tokens.intersection(_PROVIDER_TOKENS))
    rationale: List[str] = []
    warnings: List[str] = []
    recommendation = "core_or_artifact_review"
    core_allowed = "provider_neutral_only"
    next_step = "confirm_capability_domain"
    provider_strategy = "not_applicable"
    required_core_abstraction_change = False
    provider_specific_implementation_target = ""
    forbidden_core_targets: List[str] = []
    seam_summary = deployment_provider_contract_summary()
    resolved_provider = resolve_deployment_provider_for_request(
        request_text=request_text,
        capability_domain=domain if domain != "auto" else "deployment",
    )

    if domain == "deployment":
        has_core_coupling_signal = bool(tokens.intersection(_CORE_COUPLING_TOKENS))
        has_neutral_abstraction_signal = bool(tokens.intersection(_NEUTRAL_ABSTRACTION_TOKENS))
        if provider_specific and has_core_coupling_signal and not has_neutral_abstraction_signal:
            recommendation = "forbidden_core_coupling"
            provider_strategy = "provider_module_required"
            next_step = "route_provider_logic_to_deployment_provider_seam"
            provider_specific_implementation_target = str(
                ((resolved_provider.get("implementation") if isinstance(resolved_provider, dict) else {}) or {}).get("implementation_target")
                or "xyn_orchestrator.deployment_provider_contract"
            )
            forbidden_core_targets = [
                "xyn_orchestrator/xyn_api.py",
                "xyn_orchestrator/deployments.py",
                "xyn_orchestrator/instance_drivers.py",
            ]
            warnings.append("provider_specific_core_coupling_detected")
            rationale.append("Request combines provider-specific deployment intent with core-coupling language.")
            rationale.append("Provider-specific deployment logic should be implemented at the deployment-provider seam.")
        elif provider_specific:
            recommendation = "provider_artifact_module"
            provider_strategy = "provider_module_required"
            next_step = "implement_provider_behavior_in_artifact_module"
            provider_specific_implementation_target = str(
                ((resolved_provider.get("implementation") if isinstance(resolved_provider, dict) else {}) or {}).get("implementation_target")
                or "xyn_orchestrator.deployment_provider_contract"
            )
            forbidden_core_targets = [
                "xyn_orchestrator/xyn_api.py",
                "xyn_orchestrator/deployments.py",
                "xyn_orchestrator/instance_drivers.py",
            ]
            rationale.append("Request contains provider-specific deployment signals.")
            rationale.append("Core should keep orchestration and provider-neutral contracts only.")
        else:
            recommendation = "core_abstraction_orchestration"
            provider_strategy = "neutral_core_abstraction"
            required_core_abstraction_change = True
            next_step = "extend_provider_neutral_deployment_abstraction"
            rationale.append("Deployment request appears provider-neutral.")
            rationale.append("Core may host provider-neutral orchestration/state and artifact lifecycle coordination.")
    else:
        recommendation = "follow_existing_artifact_ownership"
        next_step = "resolve_artifact_ownership_and_scope_change"
        rationale.append("No deployment-specific placement rule triggered.")

    return PlacementDecision(
        policy_version=PLACEMENT_POLICY_VERSION,
        capability_domain=domain,
        recommendation=recommendation,
        provider_specific=provider_specific,
        core_allowed=core_allowed,
        rationale=rationale,
        next_step=next_step,
    ).to_dict() | {
        "architectural_placement": {
            "classification": recommendation,
            "capability_domain": domain,
            "provider_specific": provider_specific,
            "core_allowed": core_allowed,
        },
        "provider_strategy": provider_strategy,
        "required_core_abstraction_change": required_core_abstraction_change,
        "provider_specific_implementation_target": provider_specific_implementation_target,
        "forbidden_core_targets": forbidden_core_targets,
        "recommended_next_step": next_step,
        "deployment_provider_seam": seam_summary,
        "resolved_provider": resolved_provider,
        "warnings": warnings,
    }


def deployment_provider_contract_summary() -> Dict[str, object]:
    ensure_default_deployment_provider_contracts()
    default_target_contract = resolve_deployment_target_contract(selected_provider_key="aws_ssm_route53")
    return {
        "policy_version": PLACEMENT_POLICY_VERSION,
        "domain": "deployment",
        "default_deployment_target_contract": default_target_contract,
        "contracts": [
            {
                "provider_key": contract.provider_key,
                "title": contract.title,
                "implementation_kind": contract.implementation_kind,
                "execution_path": contract.execution_path,
                "artifact_extension_expected": bool(contract.artifact_extension_expected),
            }
            for contract in list_deployment_provider_contracts()
        ],
    }
