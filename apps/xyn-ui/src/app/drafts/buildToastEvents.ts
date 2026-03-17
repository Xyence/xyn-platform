type BuildToastState = "draft" | "building" | "build_blocked" | "ready" | "needs_revision" | "unavailable";

type JobLike = {
  id: string;
  updated_at?: string | null;
  created_at?: string | null;
};

type ExecutionNoteLike = {
  id: string;
  updated_at?: string | null;
  timestamp?: string | null;
};

export function deriveBuildToastEventKey(args: {
  overallState: BuildToastState;
  latestFailedJob: JobLike | null;
  latestJob: JobLike | null;
  executionNote: ExecutionNoteLike | null;
}): string | null {
  const { overallState, latestFailedJob, latestJob, executionNote } = args;
  if (!["build_blocked", "needs_revision", "ready"].includes(overallState)) return null;

  const noteTimestamp = String(executionNote?.updated_at || executionNote?.timestamp || "").trim();
  if (overallState === "ready") {
    const sourceId = String(latestJob?.id || executionNote?.id || "ready").trim();
    const sourceTimestamp = String(latestJob?.updated_at || latestJob?.created_at || noteTimestamp || "unknown").trim();
    return `${overallState}:${sourceId}:${sourceTimestamp}`;
  }

  const sourceId = String(latestFailedJob?.id || latestJob?.id || executionNote?.id || "blocked").trim();
  const sourceTimestamp = String(
    latestFailedJob?.updated_at || latestFailedJob?.created_at || latestJob?.updated_at || latestJob?.created_at || noteTimestamp || "unknown",
  ).trim();
  return `${overallState}:${sourceId}:${sourceTimestamp}`;
}
