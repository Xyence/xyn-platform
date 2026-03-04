import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  archiveBlueprint,
  createBlueprintArtifact,
  deprovisionBlueprint,
  getBlueprint,
  getBlueprintDeprovisionPlan,
  publishBlueprintArtifact,
  getRun,
  listBlueprintDevTasks,
  listBlueprints,
  reviseBlueprintArtifact,
  runDevTask,
  submitBlueprint,
  submitBlueprintWithDevTasks,
  updateArtifactRecord,
  updateBlueprint,
  listReleaseTargets,
  createReleaseTarget,
  deleteReleaseTarget,
} from "../../api/xyn";
import type {
  BlueprintCreatePayload,
  BlueprintDeprovisionPlan,
  BlueprintDetail,
  BlueprintIntent,
  BlueprintSummary,
  DevTaskSummary,
  ReleaseTarget,
} from "../../api/types";
import { extractBlueprintIntent } from "./blueprintIntent";
import { useNotifications } from "../state/notificationsStore";
import { notifyFailed, notifyQueued, notifySucceeded } from "../../lib/notifyFromJob";
import ArtifactCredibilityLayer from "../components/artifacts/ArtifactCredibilityLayer";

const emptyForm: BlueprintCreatePayload = {
  name: "",
  namespace: "core",
  description: "",
  spec_text: "",
  metadata_json: null,
};

type BlueprintsPageProps = {
  mode?: "all" | "drafts" | "versions";
};

export default function BlueprintsPage({ mode = "all" }: BlueprintsPageProps) {
  const navigate = useNavigate();
  const { blueprintId } = useParams();
  const [items, setItems] = useState<BlueprintSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<BlueprintDetail | null>(null);
  const [form, setForm] = useState<BlueprintCreatePayload>(emptyForm);
  const [metadataText, setMetadataText] = useState<string>("");
  const [devTasks, setDevTasks] = useState<DevTaskSummary[]>([]);
  const [devTaskPage, setDevTaskPage] = useState(1);
  const [releaseTargets, setReleaseTargets] = useState<ReleaseTarget[]>([]);
  const [releaseTargetForm, setReleaseTargetForm] = useState({
    name: "",
    environment: "",
    fqdn: "",
    target_instance_id: "",
    zone_name: "",
    zone_id: "",
    tls_mode: "none",
    acme_email: "",
    secret_refs_text: "",
    runtime_mode: "compose_build",
    ingress_network: "xyn-edge",
    ingress_service: "ems-web",
    ingress_port: "3000",
  });
  const [selectedReleaseTargetId, setSelectedReleaseTargetId] = useState<string>("");
  const [showDeprovisionModal, setShowDeprovisionModal] = useState(false);
  const [deprovisionPlan, setDeprovisionPlan] = useState<BlueprintDeprovisionPlan | null>(null);
  const [deprovisionMode, setDeprovisionMode] = useState<"safe" | "stop_services" | "force">("safe");
  const [deprovisionDeleteDns, setDeprovisionDeleteDns] = useState(true);
  const [deprovisionRemoveMarkers, setDeprovisionRemoveMarkers] = useState(true);
  const [deprovisionConfirmText, setDeprovisionConfirmText] = useState("");
  const [deprovisionDryRun, setDeprovisionDryRun] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previousBlueprintStatusRef = useRef<string | null>(null);
  const { push } = useNotifications();
  const devTasksPageSize = 8;
  const devTaskTotalPages = Math.max(1, Math.ceil(devTasks.length / devTasksPageSize));
  const pagedDevTasks = useMemo(() => {
    const start = (devTaskPage - 1) * devTasksPageSize;
    return devTasks.slice(start, start + devTasksPageSize);
  }, [devTasks, devTaskPage]);
  const intent = useMemo<BlueprintIntent | null>(() => extractBlueprintIntent(selected), [selected]);
  const familyChain = useMemo(() => {
    if (!selected?.family_id) return [];
    const stateOrder: Record<string, number> = { canonical: 0, provisional: 1, deprecated: 2 };
    return items
      .filter((item) => item.family_id && item.family_id === selected.family_id)
      .sort((a, b) => {
        const rankA = stateOrder[String(a.artifact_state || "").toLowerCase()] ?? 99;
        const rankB = stateOrder[String(b.artifact_state || "").toLowerCase()] ?? 99;
        if (rankA !== rankB) return rankA - rankB;
        const at = Date.parse(String(a.updated_at || "")) || 0;
        const bt = Date.parse(String(b.updated_at || "")) || 0;
        return bt - at;
      });
  }, [items, selected?.family_id]);

  const handleCreateReleaseTarget = async () => {
    if (!selected) return;
    setError(null);
    try {
      let secretRefs: Array<{ name: string; ref: string; type?: string; version?: string }> = [];
      if (releaseTargetForm.secret_refs_text.trim()) {
        secretRefs = JSON.parse(releaseTargetForm.secret_refs_text);
        if (!Array.isArray(secretRefs)) {
          throw new Error("Secret refs must be a JSON array.");
        }
      }
      await createReleaseTarget({
        blueprint_id: selected.id,
        name: releaseTargetForm.name,
        environment: releaseTargetForm.environment || undefined,
        fqdn: releaseTargetForm.fqdn,
        target_instance_id: releaseTargetForm.target_instance_id,
        dns: {
          provider: "route53",
          zone_name: releaseTargetForm.zone_name || undefined,
          zone_id: releaseTargetForm.zone_id || undefined,
          record_type: "A",
          ttl: 60,
        },
        runtime: {
          type: "docker-compose",
          transport: "ssm",
          compose_file_path: "compose.release.yml",
          remote_root: "/opt/xyn/apps/ems",
          mode: releaseTargetForm.runtime_mode,
        },
        tls: {
          mode: releaseTargetForm.tls_mode,
          provider: releaseTargetForm.tls_mode === "host-ingress" ? "traefik" : undefined,
          termination: releaseTargetForm.tls_mode === "host-ingress" ? "host" : undefined,
          acme_email: releaseTargetForm.acme_email || undefined,
          expose_http: true,
          expose_https: true,
          redirect_http_to_https: true,
        },
        ingress:
          releaseTargetForm.tls_mode === "host-ingress"
            ? {
                network: releaseTargetForm.ingress_network || "xyn-edge",
                routes: [
                  {
                    host: releaseTargetForm.fqdn,
                    service: releaseTargetForm.ingress_service || "ems-web",
                    port: Number.parseInt(releaseTargetForm.ingress_port || "3000", 10) || 3000,
                    protocol: "http",
                    health_path: "/health",
                  },
                ],
              }
            : undefined,
        secret_refs: secretRefs,
      });
      const targets = await listReleaseTargets(selected.id);
      setReleaseTargets(targets.release_targets);
      if (!selectedReleaseTargetId && targets.release_targets[0]) {
        setSelectedReleaseTargetId(targets.release_targets[0].id);
      }
      setReleaseTargetForm({
        name: "",
        environment: "",
        fqdn: "",
        target_instance_id: "",
        zone_name: "",
        zone_id: "",
        tls_mode: "none",
        acme_email: "",
        secret_refs_text: "",
        runtime_mode: "compose_build",
        ingress_network: "xyn-edge",
        ingress_service: "ems-web",
        ingress_port: "3000",
      });
      notifySucceeded(push, {
        action: "release_target.create",
        entityType: "blueprint",
        entityId: selected.id,
        title: "Release target created",
        dedupeKey: `release_target.create:${selected.id}`,
      });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleDeleteReleaseTarget = async (id: string) => {
    if (!selected) return;
    if (!confirm("Delete this release target?")) return;
    setError(null);
    try {
      await deleteReleaseTarget(id);
      const targets = await listReleaseTargets(selected.id);
      setReleaseTargets(targets.release_targets);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleSetDefaultReleaseTarget = async (id: string) => {
    if (!selected) return;
    setError(null);
    try {
      const nextMetadata = {
        ...(selected.metadata_json || {}),
        default_release_target_id: id,
      };
      await updateBlueprint(selected.id, {
        name: selected.name,
        namespace: selected.namespace,
        description: selected.description ?? "",
        spec_text: selected.spec_text ?? "",
        metadata_json: nextMetadata,
      });
      const detail = await getBlueprint(selected.id);
      setSelected(detail);
      setMetadataText(detail.metadata_json ? JSON.stringify(detail.metadata_json, null, 2) : "");
      notifySucceeded(push, {
        action: "blueprint.default_target",
        entityType: "blueprint",
        entityId: selected.id,
        title: "Default release target updated",
        dedupeKey: `blueprint.default_target:${selected.id}`,
      });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listBlueprints("", mode);
      setItems(data.blueprints);
      if (blueprintId) {
        const explicit = data.blueprints.find((item) => item.id === blueprintId);
        if (explicit) {
          setSelectedId(explicit.id);
          return;
        }
      }
      if (!selectedId && data.blueprints[0]) {
        setSelectedId(data.blueprints[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [blueprintId, selectedId, mode]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!blueprintId) return;
    if (selectedId === blueprintId) return;
    setSelectedId(blueprintId);
  }, [blueprintId, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      previousBlueprintStatusRef.current = null;
      return;
    }
    (async () => {
      try {
        const detail = await getBlueprint(selectedId);
        setSelected(detail);
        setForm({
          name: detail.name,
          namespace: detail.namespace,
          description: detail.description ?? "",
          spec_text: detail.spec_text ?? "",
          metadata_json: detail.metadata_json ?? null,
        });
        setMetadataText(detail.metadata_json ? JSON.stringify(detail.metadata_json, null, 2) : "");
        const tasks = await listBlueprintDevTasks(selectedId);
        setDevTasks(tasks.dev_tasks);
        setDevTaskPage(1);
        const targets = await listReleaseTargets(selectedId);
        setReleaseTargets(targets.release_targets);
        const defaultTargetId =
          (detail.metadata_json as Record<string, string> | null)?.default_release_target_id ?? "";
        const targetId = defaultTargetId || targets.release_targets[0]?.id || "";
        setSelectedReleaseTargetId(targetId);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId || !selected) return;
    if (selected.status !== "deprovisioning") return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      if (cancelled) return;
      try {
        const detail = await getBlueprint(selectedId);
        if (!cancelled) {
          setSelected(detail);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
        }
      }
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId, selected?.status]);

  useEffect(() => {
    if (!selectedId || !selected) {
      previousBlueprintStatusRef.current = null;
      return;
    }
    const previous = previousBlueprintStatusRef.current;
    const current = selected.status ?? null;
    if (previous === "deprovisioning" && current !== "deprovisioning") {
      (async () => {
        let failed = current !== "deprovisioned";
        let failureMessage = "See run logs for details.";
        if (selected.deprovision_last_run_id) {
          try {
            const run = await getRun(selected.deprovision_last_run_id);
            if (run.status === "failed" || run.status === "canceled") {
              failed = true;
            }
            if (run.error) {
              failureMessage = run.error;
            }
          } catch {
            // Ignore run fetch failures and fall back to blueprint status.
          }
        }
        if (failed) {
          notifyFailed(push, {
            action: "blueprint.deprovision",
            entityType: "blueprint",
            entityId: selectedId,
            title: "Deprovision failed",
            message: failureMessage,
            href: selected.deprovision_last_run_id ? `/app/runs?run=${selected.deprovision_last_run_id}` : "/app/runs",
            dedupeKey: `blueprint.deprovision:${selectedId}`,
          });
          return;
        }
        notifySucceeded(push, {
          action: "blueprint.deprovision",
          entityType: "blueprint",
          entityId: selectedId,
          title: "Deprovision completed",
          message: selected.deprovision_last_run_id || undefined,
          href: selected.deprovision_last_run_id ? `/app/runs?run=${selected.deprovision_last_run_id}` : "/app/runs",
          dedupeKey: `blueprint.deprovision:${selectedId}`,
        });
      })();
    }
    previousBlueprintStatusRef.current = current;
  }, [push, selected, selectedId]);

  useEffect(() => {
    if (devTaskPage > devTaskTotalPages) {
      setDevTaskPage(devTaskTotalPages);
    }
  }, [devTaskPage, devTaskTotalPages]);

  const handleCreate = async () => {
    try {
      setLoading(true);
      setError(null);
      const payload = { ...form };
      if (metadataText.trim().length > 0) {
        payload.metadata_json = JSON.parse(metadataText);
      } else {
        payload.metadata_json = null;
      }
      const created = await createBlueprintArtifact({
        name: payload.name || "Untitled blueprint",
        namespace: payload.namespace || "core",
        description: payload.description || "",
        spec_text: payload.spec_text || "",
        metadata_json: payload.metadata_json as Record<string, unknown> | null,
        artifact_state: mode === "drafts" ? "provisional" : "canonical",
      });
      setForm(emptyForm);
      setMetadataText("");
      await load();
      setSelectedId(created.blueprint_id);
      navigate(`/app/blueprints/${created.blueprint_id}`);
      notifySucceeded(push, {
        action: mode === "drafts" ? "blueprint.create_draft" : "blueprint.create",
        entityType: "blueprint",
        title: mode === "drafts" ? "Blueprint draft created" : "Blueprint created",
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRevise = async () => {
    if (!selected?.artifact_id) return;
    try {
      setLoading(true);
      setError(null);
      const result = await reviseBlueprintArtifact(selected.artifact_id);
      await load();
      setSelectedId(result.blueprint_id);
      navigate(`/app/blueprints/${result.blueprint_id}`);
      notifySucceeded(push, {
        action: "blueprint.revise",
        entityType: "blueprint",
        entityId: result.blueprint_id,
        title: "Provisional revision created",
        dedupeKey: `blueprint.revise:${selected.artifact_id}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handlePublishVersion = async () => {
    if (!selected?.artifact_id) return;
    if (!confirm("Publish this provisional blueprint version?")) return;
    try {
      setLoading(true);
      setError(null);
      await publishBlueprintArtifact(selected.artifact_id);
      await load();
      if (selectedId) {
        const detail = await getBlueprint(selectedId);
        setSelected(detail);
      }
      notifySucceeded(push, {
        action: "blueprint.publish_version",
        entityType: "blueprint",
        entityId: selectedId ?? undefined,
        title: "Blueprint version published",
        dedupeKey: `blueprint.publish_version:${selected.artifact_id}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDiscardProvisional = async () => {
    if (!selected?.artifact_id) return;
    if (!confirm("Discard this provisional revision?")) return;
    try {
      setLoading(true);
      setError(null);
      await updateArtifactRecord(selected.artifact_id, {
        artifact_state: "deprecated",
        reason: "discarded_provisional_revision",
      });
      const data = await listBlueprints("", mode);
      setItems(data.blueprints);
      const next = data.blueprints.find((item) => item.family_id === selected.family_id && item.artifact_state === "canonical");
      if (next) {
        setSelectedId(next.id);
        navigate(`/app/blueprints/${next.id}`);
      }
      notifySucceeded(push, {
        action: "blueprint.discard_revision",
        entityType: "blueprint",
        entityId: selectedId ?? undefined,
        title: "Provisional revision discarded",
        dedupeKey: `blueprint.discard_revision:${selected.artifact_id}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      const payload = { ...form };
      if (metadataText.trim().length > 0) {
        payload.metadata_json = JSON.parse(metadataText);
      } else {
        payload.metadata_json = null;
      }
      await updateBlueprint(selectedId, payload);
      await load();
      notifySucceeded(push, {
        action: "blueprint.update",
        entityType: "blueprint",
        entityId: selectedId,
        title: "Blueprint updated",
        dedupeKey: `blueprint.update:${selectedId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleArchive = async () => {
    if (!selectedId) return;
    if (!confirm("Archive this blueprint?")) return;
    const archivedId = selectedId;
    try {
      setLoading(true);
      setError(null);
      setSelected(null);
      setDevTasks([]);
      setReleaseTargets([]);
      setSelectedReleaseTargetId("");
      await archiveBlueprint(archivedId);
      const data = await listBlueprints("", mode);
      setItems(data.blueprints);
      const next = data.blueprints.find((item) => item.id !== archivedId) ?? null;
      if (!next) {
        setSelectedId(null);
        setSelected(null);
        setForm(emptyForm);
        setMetadataText("");
        setDevTasks([]);
        setReleaseTargets([]);
        setSelectedReleaseTargetId("");
      } else {
        setSelectedId(next.id);
      }
      notifySucceeded(push, {
        action: "blueprint.archive",
        entityType: "blueprint",
        entityId: archivedId,
        title: "Blueprint archived",
        dedupeKey: `blueprint.archive:${archivedId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const loadDeprovisionPlan = useCallback(
    async (mode: "safe" | "stop_services" | "force", deleteDns: boolean, removeMarkers: boolean) => {
      if (!selectedId) return;
      const plan = await getBlueprintDeprovisionPlan(selectedId, {
        mode,
        delete_dns: deleteDns,
        remove_runtime_markers: removeMarkers,
      });
      setDeprovisionPlan(plan);
    },
    [selectedId]
  );

  useEffect(() => {
    if (!showDeprovisionModal || !selectedId) return;
    (async () => {
      try {
        await loadDeprovisionPlan(deprovisionMode, deprovisionDeleteDns, deprovisionRemoveMarkers);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [
    showDeprovisionModal,
    selectedId,
    deprovisionMode,
    deprovisionDeleteDns,
    deprovisionRemoveMarkers,
    loadDeprovisionPlan,
  ]);

  const handleOpenDeprovision = async () => {
    if (!selected) return;
    setShowDeprovisionModal(true);
    setDeprovisionConfirmText("");
    setDeprovisionMode("safe");
    setDeprovisionDeleteDns(true);
    setDeprovisionRemoveMarkers(true);
    setDeprovisionDryRun(false);
    try {
      setError(null);
      await loadDeprovisionPlan("safe", true, true);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleExecuteDeprovision = async () => {
    if (!selectedId || !selected) return;
    try {
      setLoading(true);
      setError(null);
      const result = await deprovisionBlueprint(selectedId, {
        confirm_text: deprovisionConfirmText,
        mode: deprovisionMode,
        stop_services: deprovisionMode !== "safe",
        delete_dns: deprovisionDeleteDns,
        remove_runtime_markers: deprovisionRemoveMarkers,
        dry_run: deprovisionDryRun,
      });
      setShowDeprovisionModal(false);
      notifyQueued(push, {
        action: "blueprint.deprovision",
        entityType: "blueprint",
        entityId: selectedId,
        title: "Deprovision queued",
        message: result.run_id,
        href: result.run_id ? `/app/runs?run=${result.run_id}` : "/app/runs",
        dedupeKey: `blueprint.deprovision:${selectedId}`,
      });
      await load();
      const detail = await getBlueprint(selectedId);
      setSelected(detail);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!selectedId || !selected) return;
    const targetFqn = `${selected.namespace}.${selected.name}`;
    if (!confirm(`Submit blueprint ${targetFqn}?`)) return;
    try {
      setLoading(true);
      setError(null);
      const result = await submitBlueprint(selectedId, selectedReleaseTargetId || undefined);
      notifyQueued(push, {
        action: "blueprint.submit",
        entityType: "blueprint",
        entityId: selectedId,
        title: `Submit queued for ${targetFqn}`,
        message: result.run_id || undefined,
        href: result.run_id ? `/app/runs?run=${result.run_id}` : "/app/runs",
        dedupeKey: `blueprint.submit:${selectedId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleQueueDevTasks = async () => {
    if (!selectedId || !selected) return;
    const targetFqn = `${selected.namespace}.${selected.name}`;
    if (!confirm(`Submit and queue DevTasks for ${targetFqn}?`)) return;
    try {
      setLoading(true);
      setError(null);
      const result = await submitBlueprintWithDevTasks(selectedId, selectedReleaseTargetId || undefined);
      notifyQueued(push, {
        action: "blueprint.submit_dev_tasks",
        entityType: "blueprint",
        entityId: selectedId,
        title: `Dev tasks queued for ${targetFqn}`,
        message: result.run_id || undefined,
        href: result.run_id ? `/app/runs?run=${result.run_id}` : "/app/runs",
        dedupeKey: `blueprint.submit_dev_tasks:${selectedId}`,
      });
      const tasks = await listBlueprintDevTasks(selectedId);
      setDevTasks(tasks.dev_tasks);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRunDevTask = async (taskId: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await runDevTask(taskId);
      notifyQueued(push, {
        action: "dev_task.run",
        entityType: "blueprint",
        entityId: selectedId ?? undefined,
        title: "Dev task queued",
        message: taskId,
        href: result.run_id ? `/app/runs?run=${result.run_id}` : "/app/runs",
        dedupeKey: `dev_task.run:${taskId}`,
      });
      const tasks = await listBlueprintDevTasks(selectedId ?? "");
      setDevTasks(tasks.dev_tasks);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>{mode === "drafts" ? "Blueprint Drafts" : mode === "versions" ? "Blueprint Versions" : "Blueprints"}</h2>
          <p className="muted">
            {mode === "drafts"
              ? "Provisional blueprint artifacts awaiting publish."
              : mode === "versions"
                ? "Canonical and deprecated blueprint versions."
                : "Manage blueprint specs and submissions."}
          </p>
        </div>
        <div className="inline-actions">
          <button
            className="ghost"
            data-testid="blueprints-start-tour"
            onClick={() => window.dispatchEvent(new CustomEvent("xyn:start-tour", { detail: { slug: "platform-build-tour" } }))}
          >
            Start Tour
          </button>
          <Link className="ghost" to="/app/drafts">
            Start drafting
          </Link>
          <button className="ghost" onClick={load} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Blueprints</h3>
          </div>
          <div className="instance-list" data-tour="blueprints-list">
            {items.map((item) => {
              const projectKey = `${item.namespace}.${item.name}`;
              const draftCount = item.active_draft_count ?? 0;
              return (
                <div
                  key={item.id}
                  className={`instance-row ${selectedId === item.id ? "active" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setSelectedId(item.id);
                    navigate(`/app/blueprints/${item.id}`);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedId(item.id);
                      navigate(`/app/blueprints/${item.id}`);
                    }
                  }}
                >
                  <div>
                    <strong>{item.name}</strong>
                    <span className="muted small">{item.namespace}</span>
                    <span className="muted small">Rev {item.latest_revision ?? "—"}</span>
                    {item.artifact_state && (
                      <span className={`status-pill ${item.artifact_state === "provisional" ? "status-warn" : item.artifact_state === "canonical" ? "status-good" : ""}`}>
                        {item.artifact_state}
                      </span>
                    )}
                    {item.status && <span className="muted small">Status {item.status}</span>}
                  </div>
                  <div className="inline-actions">
                    <Link
                      className="status-pill status-info"
                      to={`/app/drafts?project_key=${encodeURIComponent(projectKey)}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      Drafts {draftCount}
                    </Link>
                  </div>
                </div>
              );
            })}
            {items.length === 0 && <p className="muted">No blueprints yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selected ? "Blueprint detail" : mode === "drafts" ? "Create blueprint draft" : "Create blueprint"}</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input value={form.name ?? ""} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </label>
            <label>
              Namespace
              <input
                value={form.namespace ?? ""}
                onChange={(event) => setForm({ ...form, namespace: event.target.value })}
              />
            </label>
            <label className="span-full">
              Description
              <input
                value={form.description ?? ""}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
            </label>
            <label>
              Blueprint specification
              <textarea
                rows={10}
                value={form.spec_text ?? ""}
                onChange={(event) => setForm({ ...form, spec_text: event.target.value })}
              />
            </label>
              <label>
                Blueprint metadata (JSON)
                <textarea
                rows={10}
                value={metadataText}
                onChange={(event) => setMetadataText(event.target.value)}
                placeholder='{"product":"EMS"}'
                />
              </label>
            </div>
          {selected && (
            <ArtifactCredibilityLayer
              artifactId={selected.artifact_id || undefined}
              titleFallback={selected.name}
              onPublish={selected.artifact_state === "provisional" ? () => void handlePublishVersion() : undefined}
              onDiscard={selected.artifact_state === "provisional" ? () => void handleDiscardProvisional() : undefined}
              onRevise={selected.artifact_state === "canonical" ? () => void handleRevise() : undefined}
              busy={loading}
            />
          )}
          {selected && (
            <div className="card-subsection">
              <h4>Lifecycle</h4>
              {selected.derived_from_artifact_id && (
                <p className="muted small">
                  Derived from{" "}
                  <Link to={`/app/artifacts/${selected.derived_from_artifact_id}`}>
                    {selected.derived_from_artifact_id}
                  </Link>
                </p>
              )}
              <p className="muted small">
                Status: <strong>{selected.status ?? "active"}</strong>
                {selected.deprovision_last_run_id ? ` • Last deprovision run ${selected.deprovision_last_run_id}` : ""}
              </p>
              {selected.artifact_state && (
                <p className="muted small">
                  Version state:{" "}
                  <span className={`status-pill ${selected.artifact_state === "provisional" ? "status-warn" : selected.artifact_state === "canonical" ? "status-good" : ""}`}>
                    {selected.artifact_state}
                  </span>
                </p>
              )}
              <p className="muted small">
                Archive hides and disables deploys. Deprovision stops runtime resources through auditable run steps.
              </p>
              {familyChain.length > 0 && (
                <div className="stack">
                  <div className="label">Version chain</div>
                  {familyChain.map((entry) => (
                    <button
                      key={entry.id}
                      className="item-row"
                      type="button"
                      onClick={() => {
                        setSelectedId(entry.id);
                        navigate(`/app/blueprints/${entry.id}`);
                      }}
                    >
                      <strong>{entry.name}</strong>
                      <span className={`status-pill ${entry.artifact_state === "provisional" ? "status-warn" : entry.artifact_state === "canonical" ? "status-good" : ""}`}>
                        {entry.artifact_state || "unknown"}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="card-subsection">
            <h4>Intent</h4>
            {intent ? (
              <div className="stack">
                <div>
                  <div className="label">Requirements summary</div>
                  <p className="muted">{intent.requirements.summary || "No summary available."}</p>
                </div>
                <div>
                  <div className="label">Functional requirements</div>
                  <ul className="intent-list">
                    {(intent.requirements.functional || []).map((entry, index) => (
                      <li key={`functional-${index}`}>{entry}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="label">UI requirements</div>
                  <ul className="intent-list">
                    {(intent.requirements.ui || []).map((entry, index) => (
                      <li key={`ui-${index}`}>{entry}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="label">Data model</div>
                  <ul className="intent-list">
                    {(intent.requirements.dataModel || []).map((entry, index) => (
                      <li key={`data-${index}`}>{entry}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="label">Operational requirements</div>
                  <ul className="intent-list">
                    {(intent.requirements.operational || []).map((entry, index) => (
                      <li key={`ops-${index}`}>{entry}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="label">Definition of done</div>
                  <ul className="intent-list">
                    {(intent.requirements.definitionOfDone || []).map((entry, index) => (
                      <li key={`dod-${index}`}>{entry}</li>
                    ))}
                  </ul>
                </div>
                <details className="intent-prompt">
                  <summary>Original prompt</summary>
                  <pre className="draft-output-pre">{intent.prompt.text}</pre>
                </details>
                {intent.transcripts && intent.transcripts.length > 0 && (
                  <div>
                    <div className="label">Transcripts</div>
                    <div className="stack">
                      {intent.transcripts.map((transcript) => (
                        <details key={transcript.id} className="intent-prompt">
                          <summary>{transcript.id}</summary>
                          {transcript.ref && <p className="muted small">{transcript.ref}</p>}
                          {transcript.text && <pre className="draft-output-pre">{transcript.text}</pre>}
                        </details>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="muted">No intent metadata stored for this blueprint (created before provenance tracking).</p>
            )}
          </div>
          <div className="form-actions">
            <button className="primary" onClick={selected ? handleUpdate : handleCreate} disabled={loading}>
              {selected ? "Save changes" : mode === "drafts" ? "Create draft" : "Create"}
            </button>
            {selected && (
              <>
                {selected.artifact_state === "canonical" && (
                  <button className="ghost" onClick={handleRevise} disabled={loading || !selected.artifact_id}>
                    Revise
                  </button>
                )}
                {selected.artifact_state === "provisional" && (
                  <>
                    <button className="primary" onClick={handlePublishVersion} disabled={loading || !selected.artifact_id}>
                      Publish
                    </button>
                    <button className="ghost" onClick={handleDiscardProvisional} disabled={loading || !selected.artifact_id}>
                      Discard
                    </button>
                  </>
                )}
                <button className="ghost" onClick={handleSubmit} disabled={loading}>
                  Submit
                </button>
                <button className="ghost" onClick={handleQueueDevTasks} disabled={loading}>
                  Submit &amp; Queue DevTasks
                </button>
                <button className="danger" onClick={handleArchive} disabled={loading}>
                  Archive
                </button>
                <button className="ghost" onClick={handleOpenDeprovision} disabled={loading}>
                  Deprovision…
                </button>
              </>
            )}
          </div>
          {selected && (
            <div className="form-grid">
              <label className="span-full">
                Release target for submit
                <select value={selectedReleaseTargetId} onChange={(event) => setSelectedReleaseTargetId(event.target.value)}>
                  <option value="">Auto-select</option>
                  {releaseTargets.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.name} — {target.fqdn}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </section>

        {selected && (
          <section className="card">
            <div className="card-header">
              <h3>Release Targets</h3>
            </div>
            {releaseTargets.length === 0 ? (
              <p className="muted">No release targets yet.</p>
            ) : (
              <div className="stack">
                {releaseTargets.map((target) => (
                  <div key={target.id} className="item-row">
                    <div>
                      <strong>{target.name}</strong>
                      <span className="muted small">{target.fqdn}</span>
                    </div>
                    <div className="inline-actions">
                      <span className="muted small">{target.tls?.mode ?? "none"}</span>
                      <button className="ghost small" onClick={() => handleSetDefaultReleaseTarget(target.id)} disabled={loading}>
                        Set default
                      </button>
                      <button className="ghost small" onClick={() => handleDeleteReleaseTarget(target.id)} disabled={loading}>
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="form-grid">
              <label>
                Name
                <input value={releaseTargetForm.name} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, name: event.target.value })} />
              </label>
              <label>
                Environment
                <input value={releaseTargetForm.environment} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, environment: event.target.value })} />
              </label>
              <label className="span-full">
                FQDN
                <input value={releaseTargetForm.fqdn} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, fqdn: event.target.value })} />
              </label>
              <label>
                Target instance ID
                <input value={releaseTargetForm.target_instance_id} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, target_instance_id: event.target.value })} />
              </label>
              <label>
                DNS zone name
                <input value={releaseTargetForm.zone_name} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, zone_name: event.target.value })} />
              </label>
              <label>
                DNS zone id
                <input value={releaseTargetForm.zone_id} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, zone_id: event.target.value })} />
              </label>
              <label>
                Runtime mode
                <select value={releaseTargetForm.runtime_mode} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, runtime_mode: event.target.value })}>
                  <option value="compose_build">compose_build</option>
                  <option value="compose_images">compose_images</option>
                </select>
              </label>
              <label>
                TLS mode
                <select value={releaseTargetForm.tls_mode} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, tls_mode: event.target.value })}>
                  <option value="none">none</option>
                  <option value="nginx+acme">nginx+acme</option>
                  <option value="host-ingress">host-ingress</option>
                  <option value="embedded">embedded</option>
                </select>
              </label>
              <label>
                Ingress network
                <input value={releaseTargetForm.ingress_network} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, ingress_network: event.target.value })} />
              </label>
              <label>
                Ingress service
                <input value={releaseTargetForm.ingress_service} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, ingress_service: event.target.value })} />
              </label>
              <label>
                Ingress port
                <input value={releaseTargetForm.ingress_port} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, ingress_port: event.target.value })} />
              </label>
              <label>
                ACME email
                <input value={releaseTargetForm.acme_email} onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, acme_email: event.target.value })} />
              </label>
              <label className="span-full">
                Secret refs (JSON array)
                <textarea
                  rows={4}
                  placeholder='[{"name":"EMS_JWT_SECRET","ref":"ssm:/xyn/ems/manager-demo/jwt_secret"}]'
                  value={releaseTargetForm.secret_refs_text}
                  onChange={(event) => setReleaseTargetForm({ ...releaseTargetForm, secret_refs_text: event.target.value })}
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="primary" onClick={handleCreateReleaseTarget} disabled={loading}>
                Add release target
              </button>
            </div>
          </section>
        )}

        {selected && (
          <section className="card">
            <div className="card-header">
              <h3>Dev Tasks</h3>
              {devTasks.length > 0 && (
                <div className="inline-actions">
                  <button className="ghost small" onClick={() => setDevTaskPage((prev) => Math.max(1, prev - 1))} disabled={devTaskPage <= 1}>
                    Prev
                  </button>
                  <span className="muted small">
                    Page {devTaskPage} / {devTaskTotalPages}
                  </span>
                  <button className="ghost small" onClick={() => setDevTaskPage((prev) => Math.min(devTaskTotalPages, prev + 1))} disabled={devTaskPage >= devTaskTotalPages}>
                    Next
                  </button>
                </div>
              )}
            </div>
            {devTasks.length === 0 ? (
              <p className="muted">No dev tasks yet.</p>
            ) : (
              <div className="stack">
                {pagedDevTasks.map((task) => (
                  <div key={task.id} className="item-row">
                    <div>
                      <strong>{task.title}</strong>
                      <span className="muted small">{task.task_type}</span>
                    </div>
                    <div className="inline-actions">
                      {task.result_run && (
                        <a className="link small" href={`/app/runs?run=${task.result_run}`}>
                          Run
                        </a>
                      )}
                      <button className="ghost small" onClick={() => handleRunDevTask(task.id)} disabled={loading}>
                        Run task
                      </button>
                      <span className="muted small">{task.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
      {showDeprovisionModal && selected && (
        <div className="modal-backdrop" onClick={() => setShowDeprovisionModal(false)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>Deprovision {selected.namespace}.{selected.name}</h3>
            <p className="muted small">
              This will run explicit undo steps and keep audit history. Type <strong>{selected.namespace}.{selected.name}</strong>{" "}
              to confirm.
            </p>
            <div className="form-grid">
              <label>
                Mode
                <select
                  value={deprovisionMode}
                  onChange={(event) => setDeprovisionMode(event.target.value as "safe" | "stop_services" | "force")}
                >
                  <option value="safe">safe</option>
                  <option value="stop_services">stop_services</option>
                  <option value="force">force</option>
                </select>
              </label>
              <label>
                Confirm text
                <input value={deprovisionConfirmText} onChange={(event) => setDeprovisionConfirmText(event.target.value)} />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={deprovisionDeleteDns}
                  onChange={(event) => setDeprovisionDeleteDns(event.target.checked)}
                />{" "}
                Delete DNS records
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={deprovisionRemoveMarkers}
                  onChange={(event) => setDeprovisionRemoveMarkers(event.target.checked)}
                />{" "}
                Remove runtime markers
              </label>
              <label>
                <input type="checkbox" checked={deprovisionDryRun} onChange={(event) => setDeprovisionDryRun(event.target.checked)} />{" "}
                Dry run only
              </label>
            </div>
            {deprovisionPlan && (
              <div className="stack">
                <p className="muted small">
                  Targets: {deprovisionPlan.summary.release_target_count} • Steps: {deprovisionPlan.summary.step_count}
                </p>
                {deprovisionPlan.warnings.length > 0 && (
                  <InlineMessage
                    tone="error"
                    title="Warnings"
                    body={deprovisionPlan.warnings.join(" ")}
                  />
                )}
                <div className="item-row">
                  <strong>Actions in plan</strong>
                </div>
                <div className="stack">
                  {deprovisionPlan.steps.map((step) => (
                    <div key={step.id} className="muted small">
                      {step.title}
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="inline-actions">
              <button className="ghost" onClick={() => setShowDeprovisionModal(false)}>
                Cancel
              </button>
              <button
                className="danger"
                disabled={
                  loading ||
                  !deprovisionConfirmText ||
                  !deprovisionPlan ||
                  (!deprovisionPlan.flags.can_execute && deprovisionMode !== "force")
                }
                onClick={handleExecuteDeprovision}
              >
                Execute deprovision
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
