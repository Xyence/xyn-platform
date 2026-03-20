import json
import os
import tempfile
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.matching import (
    DjangoMatchResultRepository,
    MatchableRecordRef,
    RecordMatchingService,
    StrategyContext,
    normalize_address,
    normalize_identifier,
    normalize_text,
)
from xyn_orchestrator.models import (
    OrchestrationPipeline,
    PlatformAuditEvent,
    ProvenanceLink,
    RecordMatchEvaluation,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
from xyn_orchestrator.xyn_api import (
    record_matching_evaluate,
    record_matching_result_detail,
    record_matching_results_collection,
)


class RecordMatchingPrimitiveTests(TestCase):
    def setUp(self):
        self._workspace_root = tempfile.TemporaryDirectory()
        self._prior_workspace_root = os.environ.get("XYN_WORKSPACE_ROOT")
        os.environ["XYN_WORKSPACE_ROOT"] = self._workspace_root.name
        self.addCleanup(self._workspace_root.cleanup)
        self.addCleanup(self._restore_workspace_root)
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"matcher-{suffix}",
            email=f"matcher-{suffix}@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"matcher-{suffix}",
            email=f"matcher-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(slug=f"match-{suffix}", name="Matching Workspace")
        self.other_workspace = Workspace.objects.create(slug=f"match-other-{suffix}", name="Other Matching Workspace")
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")
        self.pipeline = OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"matching-{suffix}",
            name="Matching Pipeline",
            created_by=self.identity,
        )
        self.run = OrchestrationLifecycleService().create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=self.pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="matching-test"),
                run_type="ingest.matching",
                target_ref={"target_type": "dataset", "target_id": "contacts"},
                initiated_by_id=str(self.identity.id),
                scope=ExecutionScope(jurisdiction="", source=""),
                metadata={"correlation_id": "corr-match", "chain_id": "chain-match"},
            )
        )

    def _restore_workspace_root(self) -> None:
        if self._prior_workspace_root is None:
            os.environ.pop("XYN_WORKSPACE_ROOT", None)
        else:
            os.environ["XYN_WORKSPACE_ROOT"] = self._prior_workspace_root

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def _candidate(self, *, source_id: str, name: str, external_id: str = "", address: str = "") -> MatchableRecordRef:
        attrs = {"name": name}
        if external_id:
            attrs["external_id"] = external_id
        if address:
            attrs["address"] = address
        return MatchableRecordRef(
            source_namespace="crm",
            source_record_type="contact",
            source_record_id=source_id,
            workspace_id=str(self.workspace.id),
            attributes=attrs,
        )

    def test_normalization_helpers(self):
        self.assertEqual(normalize_text("  Jane   DOE, LLC. "), "jane doe llc")
        self.assertEqual(normalize_identifier(" ID-123 / ABC "), "id123abc")
        self.assertEqual(normalize_address("123 North Main Street"), "123 n main st")

    def test_builtin_strategy_scoring_and_decisions(self):
        service = RecordMatchingService(repository=None)
        left = self._candidate(source_id="1", name="Jane Doe", external_id="abc-123", address="123 Main Street")
        right_exact = self._candidate(source_id="2", name="Jane Doe", external_id="ABC123", address="123 Main St")
        right_fuzzy = self._candidate(source_id="3", name="J. Doe", address="123 Main St")

        exact_eval = service.evaluate_pair(
            workspace_id=str(self.workspace.id),
            candidate_a=left,
            candidate_b=right_exact,
            strategy_key="exact_identifier",
            persist=False,
        )
        self.assertEqual(exact_eval.decision, "exact_match")
        self.assertGreaterEqual(exact_eval.score, 0.99)

        fuzzy_eval = service.evaluate_pair(
            workspace_id=str(self.workspace.id),
            candidate_a=left,
            candidate_b=right_fuzzy,
            strategy_key="fuzzy_text_similarity",
            persist=False,
        )
        self.assertIn(fuzzy_eval.decision, {"possible_match", "needs_review", "non_match", "probable_match"})
        self.assertGreaterEqual(fuzzy_eval.score, 0.0)
        self.assertLessEqual(fuzzy_eval.score, 1.0)

        composite_eval = service.evaluate_pair(
            workspace_id=str(self.workspace.id),
            candidate_a=left,
            candidate_b=right_exact,
            strategy_key="weighted_composite",
            persist=False,
        )
        self.assertIn(composite_eval.decision, {"exact_match", "probable_match"})
        self.assertTrue(composite_eval.explanation)
        self.assertTrue(composite_eval.signals)

    def test_persisted_match_results_include_explanation_and_run_context(self):
        repository = DjangoMatchResultRepository()
        service = RecordMatchingService(repository=repository)
        left = self._candidate(source_id="left-1", name="Acme Corp", external_id="acme-001")
        right = self._candidate(source_id="right-2", name="Acme Corporation", external_id="ACME001")
        context = StrategyContext(
            workspace_id=str(self.workspace.id),
            run_id=str(self.run.id),
            correlation_id="corr-match",
            chain_id="chain-match",
        )

        evaluation = service.evaluate_pair(
            workspace_id=str(self.workspace.id),
            candidate_a=left,
            candidate_b=right,
            strategy_key="weighted_composite",
            context=context,
            persist=True,
            metadata={"trigger": "unit_test"},
        )
        self.assertIn(evaluation.decision, {"exact_match", "probable_match", "possible_match"})

        row = RecordMatchEvaluation.objects.filter(workspace=self.workspace).latest("created_at")
        self.assertEqual(row.run_id, self.run.id)
        self.assertEqual(row.correlation_id, "corr-match")
        self.assertEqual(row.chain_id, "chain-match")
        self.assertEqual(row.strategy_key, "weighted_composite")
        self.assertIn("signals", row.explanation_json)

    def test_candidate_evaluation_sorts_by_score(self):
        service = RecordMatchingService(repository=None)
        target = self._candidate(source_id="base", name="Foobar Inc", external_id="foobar")
        candidates = [
            self._candidate(source_id="a", name="Foobar Inc", external_id="foobar"),
            self._candidate(source_id="b", name="Foo Bar Incorporated"),
            self._candidate(source_id="c", name="Unrelated Person"),
        ]
        ranked = service.evaluate_candidates(
            workspace_id=str(self.workspace.id),
            target=target,
            candidates=candidates,
            strategy_key="weighted_composite",
        )
        self.assertEqual(ranked[0].candidate.source_record_id, "a")
        self.assertGreaterEqual(ranked[0].evaluation.score, ranked[-1].evaluation.score)

    def test_api_evaluate_and_list_and_detail(self):
        payload = {
            "workspace_id": str(self.workspace.id),
            "strategy_key": "weighted_composite",
            "run_id": str(self.run.id),
            "correlation_id": "corr-api",
            "chain_id": "chain-api",
            "candidate_a": {
                "source_namespace": "crm",
                "source_record_type": "contact",
                "source_record_id": "left-api",
                "attributes": {"name": "Jane Doe", "external_id": "jane-1", "address": "1 Main Street"},
            },
            "candidate_b": {
                "source_namespace": "billing",
                "source_record_type": "account_contact",
                "source_record_id": "right-api",
                "attributes": {"name": "Jane Doe", "external_id": "JANE1", "address": "1 Main St"},
            },
            "persist": True,
            "metadata": {"source": "api_test"},
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            evaluate_response = record_matching_evaluate(
                self._request("/xyn/api/record-matching/evaluate", method="post", data=json.dumps(payload))
            )
        self.assertEqual(evaluate_response.status_code, 201)
        evaluate_body = json.loads(evaluate_response.content)
        self.assertTrue(evaluate_body["persisted"])
        result_id = evaluate_body["result"]["id"]

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = record_matching_results_collection(
                self._request(
                    "/xyn/api/record-matching/results",
                    data={
                        "workspace_id": str(self.workspace.id),
                        "decision": str(evaluate_body["result"]["decision"] or ""),
                    },
                )
            )
        self.assertEqual(list_response.status_code, 200)
        list_body = json.loads(list_response.content)
        self.assertTrue(any(item["id"] == result_id for item in list_body["results"]))

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            detail_response = record_matching_result_detail(
                self._request(
                    f"/xyn/api/record-matching/results/{result_id}",
                    data={"workspace_id": str(self.workspace.id)},
                ),
                result_id,
            )
        self.assertEqual(detail_response.status_code, 200)
        detail_body = json.loads(detail_response.content)
        self.assertEqual(detail_body["id"], result_id)
        self.assertEqual(detail_body["run_id"], str(self.run.id))

    def test_api_rejects_unknown_strategy_and_cross_workspace_access(self):
        payload = {
            "workspace_id": str(self.workspace.id),
            "strategy_key": "unknown",
            "candidate_a": {
                "source_namespace": "crm",
                "source_record_type": "contact",
                "source_record_id": "left",
            },
            "candidate_b": {
                "source_namespace": "crm",
                "source_record_type": "contact",
                "source_record_id": "right",
            },
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            bad_response = record_matching_evaluate(
                self._request("/xyn/api/record-matching/evaluate", method="post", data=json.dumps(payload))
            )
        self.assertEqual(bad_response.status_code, 400)

        row = RecordMatchEvaluation.objects.create(
            workspace=self.workspace,
            candidate_a_namespace="crm",
            candidate_a_type="contact",
            candidate_a_id="a",
            candidate_b_namespace="crm",
            candidate_b_type="contact",
            candidate_b_id="b",
            strategy_key="exact_identifier",
            score=1.0,
            decision="exact_match",
            confidence="exact",
            explanation_json={"summary": ["seed"]},
        )

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            forbidden = record_matching_result_detail(
                self._request(
                    f"/xyn/api/record-matching/results/{row.id}",
                    data={"workspace_id": str(self.other_workspace.id)},
                ),
                str(row.id),
            )
        self.assertEqual(forbidden.status_code, 404)

    def test_replay_dedupes_result_and_provenance(self):
        payload = {
            "workspace_id": str(self.workspace.id),
            "strategy_key": "weighted_composite",
            "run_id": str(self.run.id),
            "correlation_id": "corr-replay",
            "chain_id": "chain-replay",
            "candidate_a": {
                "source_namespace": "crm",
                "source_record_type": "contact",
                "source_record_id": "left-replay",
                "attributes": {"name": "Jane Doe", "external_id": "jane-1"},
            },
            "candidate_b": {
                "source_namespace": "billing",
                "source_record_type": "account_contact",
                "source_record_id": "right-replay",
                "attributes": {"name": "Jane Doe", "external_id": "JANE1"},
            },
            "persist": True,
            "idempotency_key": "match-idem-1",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            first = record_matching_evaluate(
                self._request("/xyn/api/record-matching/evaluate", method="post", data=json.dumps(payload))
            )
            second = record_matching_evaluate(
                self._request("/xyn/api/record-matching/evaluate", method="post", data=json.dumps(payload))
            )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(RecordMatchEvaluation.objects.filter(workspace=self.workspace).count(), 1)
        self.assertEqual(PlatformAuditEvent.objects.filter(workspace=self.workspace, event_type="record_matching.evaluated").count(), 1)
        self.assertEqual(ProvenanceLink.objects.filter(workspace=self.workspace, relationship_type="match_evaluated_from").count(), 2)

    def test_pair_fingerprint_is_order_independent(self):
        left = self._candidate(source_id="left-order", name="Acme Corp", external_id="acme-001")
        right = self._candidate(source_id="right-order", name="Acme Corporation", external_id="ACME001")
        service = RecordMatchingService(repository=DjangoMatchResultRepository())
        context = StrategyContext(
            workspace_id=str(self.workspace.id),
            run_id=str(self.run.id),
            correlation_id="corr-order",
            chain_id="chain-order",
        )
        service.evaluate_pair(
            workspace_id=str(self.workspace.id),
            candidate_a=left,
            candidate_b=right,
            strategy_key="weighted_composite",
            context=context,
            persist=True,
        )
        service.evaluate_pair(
            workspace_id=str(self.workspace.id),
            candidate_a=right,
            candidate_b=left,
            strategy_key="weighted_composite",
            context=context,
            persist=True,
        )
        self.assertEqual(RecordMatchEvaluation.objects.filter(workspace=self.workspace).count(), 1)
