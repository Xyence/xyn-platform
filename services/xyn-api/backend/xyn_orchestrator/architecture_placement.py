from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

from .deployment_provider_contract import ensure_default_deployment_provider_contracts, list_deployment_provider_contracts


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
    recommendation = "core_or_artifact_review"
    core_allowed = "provider_neutral_only"
    next_step = "confirm_capability_domain"

    if domain == "deployment":
        if provider_specific:
            recommendation = "provider_artifact_module"
            next_step = "implement_provider_behavior_in_artifact_module"
            rationale.append("Request contains provider-specific deployment signals.")
            rationale.append("Core should keep orchestration and provider-neutral contracts only.")
        else:
            recommendation = "core_abstraction_orchestration"
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
    ).to_dict()


def deployment_provider_contract_summary() -> Dict[str, object]:
    ensure_default_deployment_provider_contracts()
    return {
        "policy_version": PLACEMENT_POLICY_VERSION,
        "domain": "deployment",
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
