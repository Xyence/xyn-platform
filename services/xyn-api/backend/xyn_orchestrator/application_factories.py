from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.contrib.auth import get_user_model
from django.utils.text import slugify
from pydantic import BaseModel, Field

from .goal_planning import (
    GoalPlanningOutput,
    GoalThreadDefinition,
    GoalWorkItemDefinition,
    infer_goal_type,
    persist_goal_plan,
)
from .models import Application, ApplicationPlan, Goal, ManagedRepository, Workspace


class ApplicationFactoryDefinition(BaseModel):
    key: str
    name: str
    description: str
    intended_use_case: str
    generated_goal_families: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


class ApplicationGoalPlan(BaseModel):
    title: str
    description: str = ""
    priority: str = "normal"
    goal_type: str = "build_system"
    planning_summary: str
    resolution_notes: List[str] = Field(default_factory=list)
    threads: List[GoalThreadDefinition] = Field(default_factory=list)
    work_items: List[GoalWorkItemDefinition] = Field(default_factory=list)


class GeneratedApplicationPlan(BaseModel):
    application_name: str
    application_summary: str
    source_factory_key: str
    request_objective: str
    generated_goals: List[ApplicationGoalPlan] = Field(default_factory=list)
    ordering_hints: List[str] = Field(default_factory=list)
    dependency_hints: List[str] = Field(default_factory=list)
    resolution_notes: List[str] = Field(default_factory=list)


def _normalize_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:240] or "Application"


def _title_case_label(value: str) -> str:
    text = _normalize_name(value)
    words = [word.capitalize() for word in text.split(" ") if word]
    return " ".join(words) or "Application"


def _normalize_objective_lines(value: str) -> List[str]:
    return [line.strip() for line in re.split(r"[\r\n]+", str(value or "")) if line.strip()]


def _extract_objective_sections(objective: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {
        "core_entities": [],
        "behavior": [],
        "views": [],
        "validation": [],
    }
    text = re.sub(r"\s+", " ", str(objective or "")).strip()
    if not text:
        return sections
    section_patterns = {
        "core_entities": re.compile(
            r"core entities\s*:\s*(.*?)(?=\bbehavior\s*:|\bviews\s*/\s*usability\s*:|\bviews\s*:|\bvalidation\s*/\s*rules\s*:|\bvalidation\s*:|$)",
            re.IGNORECASE,
        ),
        "behavior": re.compile(
            r"behavior\s*:\s*(.*?)(?=\bviews\s*/\s*usability\s*:|\bviews\s*:|\bvalidation\s*/\s*rules\s*:|\bvalidation\s*:|$)",
            re.IGNORECASE,
        ),
        "views": re.compile(
            r"(?:views\s*/\s*usability|views)\s*:\s*(.*?)(?=\bvalidation\s*/\s*rules\s*:|\bvalidation\s*:|$)",
            re.IGNORECASE,
        ),
        "validation": re.compile(r"(?:validation\s*/\s*rules|validation)\s*:\s*(.*)$", re.IGNORECASE),
    }
    for section_name, pattern in section_patterns.items():
        match = pattern.search(text)
        if not match:
            continue
        body = str(match.group(1) or "").strip()
        if not body:
            continue
        if section_name == "core_entities":
            sections[section_name].extend(part.strip() for part in re.split(r"\s+(?=\d+\.)", body) if part.strip())
            continue
        sections[section_name].extend(
            re.sub(r"^\s*[-*]\s*", "", part).strip()
            for part in re.split(r"\s+-\s+", body)
            if re.sub(r"^\s*[-*]\s*", "", part).strip()
        )
    return sections


def _extract_objective_entities(objective: str) -> List[str]:
    entities: List[str] = []
    for line in _extract_objective_sections(objective).get("core_entities", []):
        cleaned_line = re.sub(r"^\s*\d+\.\s*", "", line).strip()
        token = re.split(r"\s+-\s+|:\s*", cleaned_line, maxsplit=1)[0].strip()
        normalized = _title_case_label(token)
        if normalized and normalized not in entities:
            entities.append(normalized)
    return entities


def _human_join(values: Iterable[str]) -> str:
    items = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _generic_objective_context(objective: str) -> Dict[str, str]:
    sections = _extract_objective_sections(objective)
    entities = _extract_objective_entities(objective)
    primary_entities = entities[:3]
    entity_phrase = _human_join(primary_entities) or "the first application entities"
    lead_entity = primary_entities[0] if primary_entities else "the primary domain record"
    views = sections.get("views", [])
    behavior = sections.get("behavior", [])
    validation = sections.get("validation", [])
    view_phrase = _human_join(views[:2]) or "List and inspect the first durable records"
    workflow_phrase = behavior[0] if behavior else "Create and operate the first slice through a simple user workflow"
    validation_phrase = validation[0] if validation else "Protect the first slice with the minimum durable rules"
    return {
        "entity_phrase": entity_phrase,
        "lead_entity": lead_entity,
        "view_phrase": view_phrase,
        "workflow_phrase": workflow_phrase,
        "validation_phrase": validation_phrase,
    }


def _application_plan_fingerprint(*, factory_key: str, application_name: str, objective: str, plan: GeneratedApplicationPlan) -> str:
    payload = {
        "factory_key": factory_key,
        "application_name": application_name,
        "objective": objective.strip(),
        "plan": plan.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _goal_plan(
    *,
    title: str,
    description: str,
    priority: str,
    planning_summary: str,
    resolution_notes: Iterable[str],
    threads: List[Tuple[str, str, str, str, int]],
    work_items: List[Tuple[str, str, str, str, int, List[str]]],
) -> ApplicationGoalPlan:
    return ApplicationGoalPlan(
        title=title,
        description=description,
        priority=priority,
        goal_type=infer_goal_type(title, description),
        planning_summary=planning_summary,
        resolution_notes=list(resolution_notes),
        threads=[
            GoalThreadDefinition(
                title=thread_title,
                description=thread_description,
                priority=thread_priority,
                domain=thread_domain,
                sequence=sequence,
            )
            for thread_title, thread_description, thread_priority, thread_domain, sequence in threads
        ],
        work_items=[
            GoalWorkItemDefinition(
                thread_title=thread_title,
                title=work_title,
                description=work_description,
                priority=work_priority,
                sequence=sequence,
                dependency_work_item_refs=list(dependencies),
            )
            for thread_title, work_title, work_description, work_priority, sequence, dependencies in work_items
        ],
    )


def _telecom_support_factory_plan(application_name: str, objective: str) -> GeneratedApplicationPlan:
    goals = [
        _goal_plan(
            title="Support Data and Case Foundation",
            description="Model subscribers, services, devices, and support cases as the durable telecom support foundation.",
            priority="high",
            planning_summary="Start by making the support domain durable and inspectable before workflow automation.",
            resolution_notes=["Prioritize durable support records and case intake over advanced automations."],
            threads=[
                ("Subscriber and Service Model", "Define subscriber, service, and device records.", "high", "application", 1),
                ("Case Intake", "Capture the first support-case intake flow.", "high", "workflow", 2),
            ],
            work_items=[
                ("Subscriber and Service Model", "Define subscriber, service, and device entities", "Persist the first telecom support domain entities.", "high", 1, []),
                ("Subscriber and Service Model", "Expose CRUD and detail inspection for support records", "Make support entities inspectable in Xyn and the generated app.", "high", 2, ["Define subscriber, service, and device entities"]),
                ("Case Intake", "Implement initial support case intake flow", "Create the first durable intake path for support requests.", "high", 3, []),
            ],
        ),
        _goal_plan(
            title="Support Workflow and Escalation",
            description="Add queueing, assignment, escalation, and status management for support operations.",
            priority="high",
            planning_summary="After case intake exists, add the operational workflow that telecom support staff actually uses.",
            resolution_notes=["Prefer clear operational state transitions over complex automation."],
            threads=[
                ("Case Workflow", "Model queue, assignment, and resolution states.", "normal", "workflow", 1),
                ("Escalation Workflow", "Model escalation paths and reasons.", "normal", "workflow", 2),
            ],
            work_items=[
                ("Case Workflow", "Define support case workflow states and assignment rules", "Persist operator-facing workflow state for support cases.", "normal", 1, []),
                ("Case Workflow", "Expose queue and assignment views for active support work", "Make active case work visible to operators.", "normal", 2, ["Define support case workflow states and assignment rules"]),
                ("Escalation Workflow", "Add escalation state and supporting audit fields", "Track why and when support work escalates.", "normal", 3, []),
            ],
        ),
        _goal_plan(
            title="Operations Console and Reporting",
            description="Expose support operations dashboards, reports, and service health insights.",
            priority="normal",
            planning_summary="Finish the MVP with operational visibility once the data and workflow foundation is durable.",
            resolution_notes=["Keep the first console operational and inspectable rather than broad and decorative."],
            threads=[
                ("Operations Review UI", "Build the support operations console.", "normal", "ui", 1),
                ("Reporting", "Expose basic service/case reporting and rollups.", "normal", "reporting", 2),
            ],
            work_items=[
                ("Operations Review UI", "Build the support operations console", "Create the operator-facing workspace for cases and escalations.", "normal", 1, []),
                ("Reporting", "Expose case and service health rollups", "Add the first support reporting surfaces.", "normal", 2, []),
            ],
        ),
    ]
    return GeneratedApplicationPlan(
        application_name=application_name,
        application_summary="A telecom support operations console with durable case management, escalation workflow, and operator reporting.",
        source_factory_key="telecom_support_operations_console",
        request_objective=objective,
        generated_goals=goals,
        ordering_hints=[
            "Start with support records and case intake, then add workflow, then reporting.",
        ],
        dependency_hints=[
            "Workflow depends on durable support case records.",
            "Reporting depends on support workflow state and recent activity.",
        ],
        resolution_notes=[
            "This factory emphasizes operator workflow over speculative automation.",
        ],
    )


def _reseller_portal_factory_plan(application_name: str, objective: str) -> GeneratedApplicationPlan:
    goals = [
        _goal_plan(
            title="Catalog and Offer Foundation",
            description="Model services, plans, pricing, and offer visibility for the reseller portal.",
            priority="high",
            planning_summary="Start with a durable catalog and offer model before workflow or fulfillment.",
            resolution_notes=["Keep the first slice centered on durable catalog and pricing records."],
            threads=[
                ("Catalog Model", "Persist services, plans, and offer definitions.", "high", "application", 1),
                ("Catalog Surfaces", "Expose catalog CRUD/list/detail views.", "high", "ui", 2),
            ],
            work_items=[
                ("Catalog Model", "Define service, plan, and offer entities", "Model the minimum reseller catalog records.", "high", 1, []),
                ("Catalog Surfaces", "Expose catalog CRUD and detail views", "Make offers and plans inspectable in the application.", "high", 2, ["Define service, plan, and offer entities"]),
            ],
        ),
        _goal_plan(
            title="Customer and Order Workflow",
            description="Add customer onboarding, order intake, and fulfillment state transitions.",
            priority="high",
            planning_summary="Once the catalog exists, make customer orders durable and operationally visible.",
            resolution_notes=["Prefer clear customer and order workflow over external integrations."],
            threads=[
                ("Customer Workflow", "Persist reseller customer records and onboarding state.", "normal", "workflow", 1),
                ("Order Workflow", "Persist order intake and fulfillment state.", "normal", "workflow", 2),
            ],
            work_items=[
                ("Customer Workflow", "Define reseller customer and tenant entities", "Create the first customer-side durable model.", "normal", 1, []),
                ("Order Workflow", "Implement order intake and fulfillment workflow", "Track order lifecycle through durable workflow state.", "normal", 2, ["Define reseller customer and tenant entities"]),
            ],
        ),
        _goal_plan(
            title="Operations and Revenue Visibility",
            description="Expose reseller operations, revenue tracking, and issue review visibility.",
            priority="normal",
            planning_summary="Complete the MVP with operational visibility into orders, issues, and revenue status.",
            resolution_notes=["Keep external billing and provisioning integrations future-facing."],
            threads=[
                ("Reseller Review UI", "Build the operator-facing reseller portal surfaces.", "normal", "ui", 1),
                ("Revenue Reporting", "Expose revenue and order-state rollups.", "normal", "reporting", 2),
            ],
            work_items=[
                ("Reseller Review UI", "Build the reseller operations review UI", "Surface orders, customers, and issues in an operator workspace.", "normal", 1, []),
                ("Revenue Reporting", "Expose revenue and fulfillment rollups", "Add reporting for order and revenue status.", "normal", 2, []),
            ],
        ),
    ]
    return GeneratedApplicationPlan(
        application_name=application_name,
        application_summary="A reseller portal with catalog management, customer/order workflow, and operational revenue visibility.",
        source_factory_key="reseller_portal",
        request_objective=objective,
        generated_goals=goals,
        ordering_hints=["Start with catalog and offer records before customer/order workflow."],
        dependency_hints=["Customer and order workflow depends on the catalog/offer foundation."],
        resolution_notes=["This factory keeps provisioning and billing integrations out of the initial MVP."],
    )


def _generic_application_plan(application_name: str, objective: str) -> GeneratedApplicationPlan:
    context = _generic_objective_context(objective)
    goals = [
        _goal_plan(
            title="Core Domain Foundation",
            description=f"Define durable records for {context['entity_phrase']} and make the first slice inspectable.",
            priority="high",
            planning_summary=(
                f"Start with {context['lead_entity']} and the related records needed for the first user-visible slice, "
                f"then make that slice inspectable through {context['view_phrase'].lower()}."
            ),
            resolution_notes=["Prefer one vertical slice over broad component enumeration."],
            threads=[
                ("Core Domain Slice", f"Define the durable model for {context['entity_phrase']}.", "high", "application", 1),
                ("Operational Surface", f"Expose the first user-facing inspection flow: {context['view_phrase']}.", "normal", "ui", 2),
            ],
            work_items=[
                (
                    "Core Domain Slice",
                    f"Define the {context['entity_phrase']} entity model",
                    f"Model {context['entity_phrase']} as durable Xyn records with the relationships and statuses needed for the first slice.",
                    "high",
                    1,
                    [],
                ),
                (
                    "Core Domain Slice",
                    f"Implement the first {context['lead_entity']} workflow slice",
                    f"Deliver the smallest runnable slice that proves the objective: {context['workflow_phrase']}.",
                    "high",
                    2,
                    [f"Define the {context['entity_phrase']} entity model"],
                ),
                (
                    "Operational Surface",
                    f"Expose {context['lead_entity']} list and detail inspection",
                    f"Make the slice inspectable in panels and generated app surfaces through {context['view_phrase']}.",
                    "normal",
                    3,
                    [f"Implement the first {context['lead_entity']} workflow slice"],
                ),
            ],
        ),
        _goal_plan(
            title="Workflow and Stabilization",
            description=f"Add the first operator workflow for {context['lead_entity']} and validate the slice with tests and runtime visibility.",
            priority="normal",
            planning_summary=(
                f"Once the first {context['lead_entity'].lower()} slice exists, add the operator workflow and validation rules "
                f"that prove it is usable and stable."
            ),
            resolution_notes=["Keep the first workflow operational and testable before broadening scope."],
            threads=[
                ("Operator Workflow", f"Add the first operator-facing workflow for {context['lead_entity']}.", "normal", "workflow", 1),
                ("Stabilization", f"Validate the first slice and protect rules like: {context['validation_phrase']}.", "normal", "quality", 2),
            ],
            work_items=[
                (
                    "Operator Workflow",
                    f"Define the first {context['lead_entity']} workflow state",
                    f"Persist the minimum workflow needed to operate the slice: {context['workflow_phrase']}.",
                    "normal",
                    1,
                    [],
                ),
                (
                    "Stabilization",
                    f"Validate the {context['lead_entity']} slice with tests and runtime observability",
                    f"Prove the initial application slice is stable enough to extend and enforce rules such as {context['validation_phrase']}.",
                    "normal",
                    2,
                    [],
                ),
            ],
        ),
    ]
    return GeneratedApplicationPlan(
        application_name=application_name,
        application_summary="A factory-generated Xyn application plan focused on the smallest durable MVP slice.",
        source_factory_key="generic_application_mvp",
        request_objective=objective,
        generated_goals=goals,
        ordering_hints=["Begin with one vertical slice, then add workflow and stabilization."],
        dependency_hints=["Operational workflow depends on the first durable slice existing."],
        resolution_notes=["This generic factory intentionally stays MVP-first and review-oriented."],
    )


BUILT_IN_APPLICATION_FACTORIES: List[ApplicationFactoryDefinition] = [
    ApplicationFactoryDefinition(
        key="telecom_support_operations_console",
        name="Telecom Support Operations Console",
        description="Generates a support-operations plan centered on case intake, workflow, escalation, and reporting.",
        intended_use_case="Telecom support teams that need durable support case and service operations workflows.",
        generated_goal_families=[
            "Support Data and Case Foundation",
            "Support Workflow and Escalation",
            "Operations Console and Reporting",
        ],
        assumptions=[
            "Prioritizes durable support records before dashboard breadth.",
        ],
    ),
    ApplicationFactoryDefinition(
        key="reseller_portal",
        name="Reseller Portal",
        description="Generates a reseller-operations plan centered on catalog, customer/order workflow, and revenue visibility.",
        intended_use_case="Marketplace/workflow applications where offer management and order workflow matter.",
        generated_goal_families=[
            "Catalog and Offer Foundation",
            "Customer and Order Workflow",
            "Operations and Revenue Visibility",
        ],
        assumptions=[
            "Leaves billing/provisioning integrations out of the first slice.",
        ],
    ),
    ApplicationFactoryDefinition(
        key="generic_application_mvp",
        name="Generic Application MVP",
        description="Generates a small vertical-slice-first application plan when no domain-specific factory is a better fit.",
        intended_use_case="Fallback application planning for supervised MVP generation.",
        generated_goal_families=[
            "Core Domain Foundation",
            "Workflow and Stabilization",
        ],
        assumptions=[
            "Favors one vertical slice over broad architecture coverage.",
        ],
    ),
]


FACTORY_PLAN_BUILDERS = {
    "telecom_support_operations_console": _telecom_support_factory_plan,
    "reseller_portal": _reseller_portal_factory_plan,
    "generic_application_mvp": _generic_application_plan,
}


def list_application_factories() -> List[ApplicationFactoryDefinition]:
    return list(BUILT_IN_APPLICATION_FACTORIES)


def get_application_factory(factory_key: str) -> Optional[ApplicationFactoryDefinition]:
    key = str(factory_key or "").strip()
    for definition in BUILT_IN_APPLICATION_FACTORIES:
        if definition.key == key:
            return definition
    return None


def infer_application_factory_key(*, objective: str, requested_factory_key: str = "") -> str:
    explicit = str(requested_factory_key or "").strip()
    if explicit and get_application_factory(explicit):
        return explicit
    lowered = str(objective or "").strip().lower()
    if any(marker in lowered for marker in ("telecom", "support console", "support operations", "support ops", "case escalation")):
        return "telecom_support_operations_console"
    if any(marker in lowered for marker in ("reseller portal", "reseller", "marketplace", "malware-services", "portal")):
        return "reseller_portal"
    return "generic_application_mvp"


def infer_application_name(objective: str, explicit_name: str = "") -> str:
    if str(explicit_name or "").strip():
        return _normalize_name(explicit_name)
    text = _normalize_name(objective)
    for prefix in (
        "build ",
        "create ",
        "generate ",
        "make ",
        "start ",
        "plan for ",
        "create an application plan for ",
        "generate a plan for ",
    ):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    text = re.sub(r"^(an?\s+)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(application|system|project|portal|console)$", "", text, flags=re.IGNORECASE)
    return _title_case_label(text)


def generate_application_plan(*, objective: str, factory_key: str = "", application_name: str = "") -> Tuple[ApplicationFactoryDefinition, GeneratedApplicationPlan]:
    resolved_factory_key = infer_application_factory_key(objective=objective, requested_factory_key=factory_key)
    definition = get_application_factory(resolved_factory_key) or get_application_factory("generic_application_mvp")
    if definition is None:
        raise ValueError("application factory is not available")
    resolved_name = infer_application_name(objective, application_name)
    plan_builder = FACTORY_PLAN_BUILDERS[definition.key]
    return definition, plan_builder(resolved_name, objective)


def create_or_get_application_plan(
    *,
    workspace: Workspace,
    objective: str,
    requested_by,
    source_conversation_id: str = "",
    factory_key: str = "",
    application_name: str = "",
    target_repository: ManagedRepository | None = None,
) -> Tuple[ApplicationPlan, ApplicationFactoryDefinition, GeneratedApplicationPlan, bool]:
    definition, generated_plan = generate_application_plan(
        objective=objective,
        factory_key=factory_key,
        application_name=application_name,
    )
    fingerprint = _application_plan_fingerprint(
        factory_key=definition.key,
        application_name=generated_plan.application_name,
        objective=objective,
        plan=generated_plan,
    )
    defaults = {
        "name": generated_plan.application_name,
        "summary": generated_plan.application_summary,
        "source_factory_key": definition.key,
        "source_conversation_id": str(source_conversation_id or "").strip(),
        "requested_by": requested_by,
        "target_repository": target_repository,
        "request_objective": str(objective or "").strip(),
        "plan_json": generated_plan.model_dump(mode="json"),
        "status": "review",
    }
    plan = (
        ApplicationPlan.objects.filter(workspace=workspace, plan_fingerprint=fingerprint)
        .select_related("application")
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if plan is not None and _application_plan_is_historical(plan):
        _retire_application_plan_fingerprint(plan)
        plan = None
    created = False
    if plan is None:
        plan = ApplicationPlan.objects.create(
            workspace=workspace,
            plan_fingerprint=fingerprint,
            **defaults,
        )
        created = True
    if not created:
        dirty = False
        for field, value in defaults.items():
            if getattr(plan, field) != value:
                setattr(plan, field, value)
                dirty = True
        if dirty:
            plan.save(update_fields=["name", "summary", "source_factory_key", "source_conversation_id", "requested_by", "target_repository", "request_objective", "plan_json", "status", "updated_at"])
    return plan, definition, generated_plan, created


def apply_application_plan(*, application_plan: ApplicationPlan, user) -> Tuple[Application, bool]:
    if application_plan.application_id and application_plan.application and application_plan.application.status != "archived":
        return application_plan.application, False
    if application_plan.application_id and application_plan.application and application_plan.application.status == "archived":
        application_plan.application = None
        application_plan.status = "review"
        application_plan.save(update_fields=["application", "status", "updated_at"])
    payload = application_plan.plan_json if isinstance(application_plan.plan_json, dict) else {}
    generated_plan = GeneratedApplicationPlan.model_validate(payload)
    existing_application = (
        Application.objects.filter(workspace=application_plan.workspace, plan_fingerprint=application_plan.plan_fingerprint)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if existing_application is not None and existing_application.status == "archived":
        _retire_application_fingerprint(existing_application)
        existing_application = None
    application_defaults = {
        "name": application_plan.name,
        "summary": application_plan.summary,
        "source_factory_key": application_plan.source_factory_key,
        "source_conversation_id": application_plan.source_conversation_id,
        "requested_by": application_plan.requested_by,
        "target_repository": application_plan.target_repository,
        "request_objective": application_plan.request_objective,
        "status": "active",
        "metadata_json": {
            "ordering_hints": generated_plan.ordering_hints,
            "dependency_hints": generated_plan.dependency_hints,
            "resolution_notes": generated_plan.resolution_notes,
        },
    }
    if existing_application is None:
        application = Application.objects.create(
            workspace=application_plan.workspace,
            plan_fingerprint=application_plan.plan_fingerprint,
            **application_defaults,
        )
        created = True
    else:
        application = existing_application
        created = False
    if created:
        user_model = get_user_model()
        for goal_seed in generated_plan.generated_goals:
            goal = Goal.objects.create(
                workspace=application_plan.workspace,
                application=application,
                title=goal_seed.title[:240],
                description=goal_seed.description,
                source_conversation_id=application_plan.source_conversation_id,
                requested_by=application_plan.requested_by,
                goal_type=goal_seed.goal_type or infer_goal_type(goal_seed.title, goal_seed.description),
                planning_status="proposed",
                priority=goal_seed.priority,
                planning_summary=goal_seed.planning_summary,
                resolution_notes_json=list(goal_seed.resolution_notes),
            )
            plan = GoalPlanningOutput(
                goal_id=str(goal.id),
                planning_summary=goal_seed.planning_summary,
                threads=goal_seed.threads,
                work_items=goal_seed.work_items,
                resolution_notes=goal_seed.resolution_notes,
            )
            persist_goal_plan(goal, plan, user=user if isinstance(user, user_model) else None)
    elif application_plan.target_repository_id and application.target_repository_id != application_plan.target_repository_id:
        application.target_repository = application_plan.target_repository
        application.save(update_fields=["target_repository", "updated_at"])
    application_plan.application = application
    application_plan.status = "applied"
    application_plan.save(update_fields=["application", "status", "updated_at"])
    return application, created


def _retired_fingerprint(fingerprint: str) -> str:
    return f"{fingerprint}:retired:{uuid.uuid4().hex[:8]}"


def _application_plan_is_historical(plan: ApplicationPlan) -> bool:
    return plan.status == "canceled" or bool(plan.application_id and plan.application and plan.application.status == "archived")


def _retire_application_fingerprint(application: Application) -> None:
    application.plan_fingerprint = _retired_fingerprint(application.plan_fingerprint or uuid.uuid4().hex)
    application.save(update_fields=["plan_fingerprint", "updated_at"])


def _retire_application_plan_fingerprint(plan: ApplicationPlan) -> None:
    if plan.application_id and plan.application and plan.application.plan_fingerprint == plan.plan_fingerprint:
        _retire_application_fingerprint(plan.application)
    plan.plan_fingerprint = _retired_fingerprint(plan.plan_fingerprint or uuid.uuid4().hex)
    if plan.status != "canceled":
        plan.status = "canceled"
        plan.save(update_fields=["plan_fingerprint", "status", "updated_at"])
        return
    plan.save(update_fields=["plan_fingerprint", "updated_at"])
