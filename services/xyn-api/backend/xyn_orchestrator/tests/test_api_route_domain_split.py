from django.test import SimpleTestCase
from django.urls import resolve

from xyn_orchestrator.api.appspec import composer_state
from xyn_orchestrator.api.artifacts import artifacts_collection
from xyn_orchestrator.api.orchestration import orchestration_runs_collection
from xyn_orchestrator.api.solutions import applications_collection
from xyn_orchestrator.api.system import system_readiness
from xyn_orchestrator.api.workspaces import workspaces_collection


class ApiRouteDomainSplitTests(SimpleTestCase):
    def test_routes_still_resolve_to_same_view_callables(self):
        self.assertIs(resolve('/xyn/api/artifacts').func, artifacts_collection)
        self.assertIs(resolve('/xyn/api/workspaces').func, workspaces_collection)
        self.assertIs(resolve('/xyn/api/applications').func, applications_collection)
        self.assertIs(resolve('/xyn/api/orchestration/runs').func, orchestration_runs_collection)
        self.assertIs(resolve('/xyn/api/composer/state').func, composer_state)
        self.assertIs(resolve('/xyn/api/system/readiness').func, system_readiness)
