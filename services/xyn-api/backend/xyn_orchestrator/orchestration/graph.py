from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .definitions import JobDefinition


@dataclass(frozen=True)
class DependencySnapshot:
    completed: frozenset[str]
    failed: frozenset[str]
    changed: frozenset[str]


class JobDependencyGraph:
    """In-memory dependency graph for a pipeline definition."""

    def __init__(self, jobs: tuple[JobDefinition, ...]):
        self._jobs_by_key: dict[str, JobDefinition] = {}
        self._upstream_by_job: dict[str, set[str]] = defaultdict(set)
        self._downstream_by_job: dict[str, set[str]] = defaultdict(set)

        for job in jobs:
            key = str(job.key or "").strip()
            if not key:
                raise ValueError("job key is required")
            if key in self._jobs_by_key:
                raise ValueError(f"duplicate job key: {key}")
            self._jobs_by_key[key] = job

        for job in jobs:
            for dependency_key in job.dependencies:
                upstream = str(dependency_key or "").strip()
                if upstream not in self._jobs_by_key:
                    raise ValueError(f"job {job.key} depends on unknown job {upstream}")
                self._upstream_by_job[job.key].add(upstream)
                self._downstream_by_job[upstream].add(job.key)

    def jobs(self) -> tuple[JobDefinition, ...]:
        return tuple(self._jobs_by_key.values())

    def topological_order(self) -> list[JobDefinition]:
        indegree: dict[str, int] = {
            key: len(self._upstream_by_job.get(key, set()))
            for key in self._jobs_by_key.keys()
        }
        queue = deque(sorted([key for key, degree in indegree.items() if degree == 0]))
        ordered: list[JobDefinition] = []

        while queue:
            key = queue.popleft()
            ordered.append(self._jobs_by_key[key])
            for downstream in sorted(self._downstream_by_job.get(key, set())):
                indegree[downstream] -= 1
                if indegree[downstream] == 0:
                    queue.append(downstream)

        if len(ordered) != len(self._jobs_by_key):
            raise ValueError("job dependency graph contains a cycle")
        return ordered

    def ready_jobs(self, snapshot: DependencySnapshot) -> list[JobDefinition]:
        ready: list[JobDefinition] = []
        for job in self.topological_order():
            if job.key in snapshot.completed or job.key in snapshot.failed:
                continue
            upstream = self._upstream_by_job.get(job.key, set())
            if not upstream.issubset(snapshot.completed):
                continue
            if upstream.intersection(snapshot.failed):
                continue
            if job.only_if_upstream_changed and upstream and not upstream.intersection(snapshot.changed):
                continue
            ready.append(job)
        return ready

    def downstream_jobs(self, job_key: str) -> tuple[JobDefinition, ...]:
        keys = sorted(self._downstream_by_job.get(str(job_key or "").strip(), set()))
        return tuple(self._jobs_by_key[key] for key in keys)
