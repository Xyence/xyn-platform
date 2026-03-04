import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { generateIntentScript, getWorkflow, updateIntentScript } from "../../api/xyn";
import type { IntentScript, WorkflowDetail } from "../../api/types";
import IntentScriptModal from "../components/artifacts/IntentScriptModal";

export default function TourDetailPage() {
  const { workflowId } = useParams();
  const [workflow, setWorkflow] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [script, setScript] = useState<IntentScript | null>(null);
  const [scriptOpen, setScriptOpen] = useState(false);
  const [scriptSaving, setScriptSaving] = useState(false);

  useEffect(() => {
    if (!workflowId) return;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await getWorkflow(workflowId);
        setWorkflow(payload.workflow);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    })();
  }, [workflowId]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>{workflow?.title || "Tour detail"}</h2>
          <p className="muted">{workflow?.description || "Published guided workflow."}</p>
        </div>
        <div className="inline-actions">
          {workflow && (
            <>
              <button
                className="ghost"
                onClick={() => window.dispatchEvent(new CustomEvent("xyn:start-tour", { detail: { slug: workflow.slug, workflowId: workflow.id } }))}
              >
                Start Tour
              </button>
              <button
                className="ghost"
                disabled={scriptSaving}
                onClick={async () => {
                  setScriptSaving(true);
                  try {
                    const generated = await generateIntentScript({
                      scope_type: "tour",
                      scope_ref_id: workflow.id,
                      audience: "developer",
                      length_target: "medium",
                    });
                    setScript(generated.item);
                    setScriptOpen(true);
                  } finally {
                    setScriptSaving(false);
                  }
                }}
              >
                Generate Intent Script
              </button>
            </>
          )}
          <Link className="ghost" to="/app/tours">
            Back to tours
          </Link>
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <section className="card stack">
        {loading && <p className="muted">Loading tour…</p>}
        {!loading && workflow && (
          <>
            <div className="muted small">{workflow.slug} · {workflow.status} · {workflow.category_name || workflow.category}</div>
            <div className="stack">
              {(workflow.workflow_spec_json?.steps || []).map((step, index) => (
                <div key={step.id || index} className="item-row">
                  <div>
                    <strong>{index + 1}. {step.title || step.id}</strong>
                    <div className="muted small">{step.route || "no route"} · {step.type}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </section>
      <IntentScriptModal
        open={scriptOpen}
        script={script}
        saving={scriptSaving}
        onClose={() => setScriptOpen(false)}
        onSave={async (next) => {
          setScriptSaving(true);
          try {
            const saved = await updateIntentScript(next.intent_script_id, {
              title: next.title,
              status: next.status,
              script_text: next.script_text,
              script_json: next.script_json as Record<string, unknown>,
            });
            setScript(saved.item);
          } finally {
            setScriptSaving(false);
          }
        }}
      />
    </>
  );
}
