import { useEffect, useMemo, useState } from "react";
import { getRulesBrowser } from "../../../api/xyn";
import type { RuleBrowserBundle, RuleBrowserResponse } from "../../../api/types";

function badgeTone(kind: "enforced" | "documented" | "editable" | "readonly" | "owner"): string {
  if (kind === "enforced") return "badge success";
  if (kind === "documented") return "badge warning";
  if (kind === "editable") return "badge";
  if (kind === "readonly") return "badge muted";
  return "badge muted";
}

function ownershipLabel(raw: string): string {
  const value = String(raw || "").trim();
  if (!value) return "Unknown";
  if (value === "generated_application") return "App-managed";
  if (value === "platform" || value === "platform_managed") return "Platform-managed";
  if (value === "workspace") return "Workspace-managed";
  return value.replace(/[_-]+/g, " ");
}

export default function RulesBrowserPanel({
  workspaceId,
  artifactSlug,
  appSlug,
  query,
  editableOnly,
  systemOnly,
}: {
  workspaceId?: string;
  artifactSlug?: string;
  appSlug?: string;
  query?: string;
  editableOnly?: boolean;
  systemOnly?: boolean;
}) {
  const [payload, setPayload] = useState<RuleBrowserResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedBundleId, setSelectedBundleId] = useState("");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getRulesBrowser({
          workspaceId,
          artifactSlug,
          appSlug,
          q: query,
          editable: editableOnly,
          system: systemOnly,
        });
        if (!active) return;
        setPayload(next);
        const bundles = Array.isArray(next.bundles) ? next.bundles : [];
        if (bundles.length === 1) {
          setSelectedBundleId(String(bundles[0]?.bundle_id || ""));
        } else {
          setSelectedBundleId("");
        }
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load rules");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [appSlug, artifactSlug, editableOnly, query, systemOnly, workspaceId]);

  const bundles = useMemo(() => (Array.isArray(payload?.bundles) ? payload?.bundles : []), [payload?.bundles]);
  const activeBundle = useMemo<RuleBrowserBundle | null>(
    () => bundles.find((entry) => String(entry.bundle_id) === String(selectedBundleId)) || null,
    [bundles, selectedBundleId]
  );
  const visibleRules = useMemo(() => {
    const rows = Array.isArray(payload?.rules) ? payload.rules : [];
    if (!selectedBundleId) return rows;
    return rows.filter((row) => String(row.source_policy_bundle?.bundle_id || "") === String(selectedBundleId));
  }, [payload?.rules, selectedBundleId]);

  const grouped = useMemo(() => {
    const map = new Map<string, { label: string; rows: typeof visibleRules }>();
    visibleRules.forEach((row) => {
      const key = String(row.family || "other");
      const existing = map.get(key);
      if (existing) {
        existing.rows.push(row);
        return;
      }
      map.set(key, { label: String(row.family_label || row.family || "Other"), rows: [row] });
    });
    return [...map.entries()].map(([family, value]) => ({ family, label: value.label, rows: value.rows }));
  }, [visibleRules]);

  if (loading) return <p className="muted">Loading rules…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No rules available.</p>;

  return (
    <div className="ems-panel-body" data-testid="rules-browser-panel">
      <h3 style={{ marginTop: 0 }}>Rules Browser</h3>
      <p className="muted small">
        {activeBundle
          ? `${activeBundle.title} · ${activeBundle.app_slug || "app"}`
          : "Select a policy bundle to inspect grouped rules."}
      </p>

      {bundles.length > 1 ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="field-label">Policy Bundles</div>
          <p className="muted small">Choose which app/artifact policy bundle to inspect.</p>
          <div style={{ display: "grid", gap: 8 }}>
            {bundles.map((bundle) => {
              const selected = String(bundle.bundle_id) === String(selectedBundleId);
              return (
                <button
                  key={bundle.bundle_id}
                  type="button"
                  className={`ghost sm${selected ? " active" : ""}`}
                  onClick={() => setSelectedBundleId(bundle.bundle_id)}
                >
                  {bundle.title} · {bundle.rule_count} rules
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      {!visibleRules.length ? (
        <p className="muted" style={{ marginTop: 12 }}>
          No matching rules for the current filters.
        </p>
      ) : null}

      {grouped.map((group) => (
        <section className="card" key={group.family} style={{ marginTop: 12 }}>
          <div className="field-label">{group.label}</div>
          <ul className="muted" style={{ marginTop: 8 }}>
            {group.rows.map((rule) => (
              <li key={rule.id} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <strong>{rule.title}</strong>
                  <span className={badgeTone(rule.enforced ? "enforced" : "documented")}>
                    {rule.enforced ? "Enforced" : "Documented-only"}
                  </span>
                  <span className={badgeTone("owner")}>{ownershipLabel(rule.ownership)}</span>
                  <span className={badgeTone(rule.editable ? "editable" : "readonly")}>{rule.editable ? "Editable" : "Read-only"}</span>
                  <span className="badge muted">{rule.scope || "generated_runtime"}</span>
                </div>
                {rule.description ? <div className="small muted" style={{ marginTop: 4 }}>{rule.description}</div> : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
