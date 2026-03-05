import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import { getAppJob } from "../../api/xyn";
import type { AppJob } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

type JobDetailTab = "logs" | "output" | "input";

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export default function JobDetailPage({
  workspaceId,
  workspaceName,
  workspaceColor,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
}) {
  const params = useParams();
  const navigate = useNavigate();
  const jobId = String(params.jobId || "").trim();
  const [job, setJob] = useState<AppJob | null>(null);
  const [tab, setTab] = useState<JobDetailTab>("logs");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shouldPoll = useMemo(() => {
    const token = String(job?.status || "").toLowerCase();
    return token === "queued" || token === "running";
  }, [job?.status]);

  const load = useCallback(async () => {
    if (!workspaceId || !jobId) return;
    try {
      setLoading(true);
      setError(null);
      const payload = await getAppJob(jobId, workspaceId);
      setJob(payload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [jobId, workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!shouldPoll) return;
    const interval = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(interval);
  }, [load, shouldPoll]);

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} />
      <div className="page-header">
        <div>
          <h2>Job Detail</h2>
          <p className="muted">Status and logs for job execution.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => navigate(toWorkspacePath(workspaceId, "jobs"))}>
            Back to Jobs
          </button>
          <button className="ghost" onClick={() => void load()} disabled={loading || !workspaceId}>
            Refresh
          </button>
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <section className="card">
        <div className="card-header">
          <h3>{job?.type || "Job"}</h3>
          <span className="chip">{job?.status || "unknown"}</span>
        </div>
        <p className="muted small">Job ID: {job?.id || jobId}</p>
        <Tabs
          value={tab}
          onChange={(next) => setTab(next)}
          options={[
            { value: "logs", label: "Logs" },
            { value: "output", label: "Output" },
            { value: "input", label: "Input" },
          ]}
          ariaLabel="Job detail tabs"
        />
        {tab === "logs" && <pre className="code-block">{job?.logs_text || "(no logs)"}</pre>}
        {tab === "output" && <pre className="code-block">{prettyJson(job?.output_json || {})}</pre>}
        {tab === "input" && <pre className="code-block">{prettyJson(job?.input_json || {})}</pre>}
      </section>
    </>
  );
}
