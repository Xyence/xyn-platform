import { useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { applySeedPacks, getSeedPack, listSeedPacks } from "../../api/xyn";
import type { SeedPackStatus } from "../../api/types";

export default function SeedPacksPage() {
  const [packs, setPacks] = useState<SeedPackStatus[]>([]);
  const [selectedSlug, setSelectedSlug] = useState("");
  const [selectedPack, setSelectedPack] = useState<SeedPackStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const selected = useMemo(() => selectedPack || packs.find((pack) => pack.slug === selectedSlug) || null, [packs, selectedSlug, selectedPack]);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listSeedPacks();
      const next = data.packs || [];
      setPacks(next);
      if (!selectedSlug && next.length) {
        setSelectedSlug(next[0].slug);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (slug: string) => {
    try {
      const data = await getSeedPack(slug);
      setSelectedPack(data.pack || null);
    } catch {
      setSelectedPack(null);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!selectedSlug) {
      setSelectedPack(null);
      return;
    }
    loadDetail(selectedSlug);
  }, [selectedSlug]);

  const runApply = async (payload: { apply_core?: boolean; pack_slugs?: string[]; dry_run?: boolean }, label: string) => {
    try {
      setActionBusy(label);
      setError(null);
      setMessage(null);
      const result = await applySeedPacks(payload);
      const summary = result.summary || { created: 0, updated: 0, unchanged: 0, skipped: 0, failed: 0 };
      setMessage(
        `${label}: created ${summary.created}, updated ${summary.updated}, unchanged ${summary.unchanged}, skipped ${summary.skipped}, failed ${summary.failed}.`
      );
      await load();
      if (selectedSlug) await loadDetail(selectedSlug);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(null);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Seed Packs</h2>
          <p className="muted">Versioned baseline data provisioning for Context Packs and future system defaults.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => void load()} disabled={loading || !!actionBusy}>
            Refresh
          </button>
          <button className="ghost" onClick={() => void runApply({ apply_core: true, dry_run: true }, "Dry run core")} disabled={loading || !!actionBusy}>
            Dry run core
          </button>
          <button className="primary" onClick={() => void runApply({ apply_core: true }, "Apply core")} disabled={loading || !!actionBusy}>
            Apply core seeds
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Seed update" body={message} />}

      <div className="layout">
        <section className="card list-pane">
          <div className="card-header">
            <h3>Seed packs</h3>
          </div>
          <div className="list-scroll">
            {packs.map((pack) => {
              const active = selectedSlug === pack.slug;
              return (
                <button key={pack.slug} className={`list-row ${active ? "active" : ""}`} type="button" onClick={() => setSelectedSlug(pack.slug)}>
                  <strong>{pack.name}</strong>
                  <div className="muted small">{pack.slug} · {pack.scope} · {pack.version}</div>
                  <div className="muted small">Missing {pack.missing_count} · Drifted {pack.drifted_count}</div>
                </button>
              );
            })}
            {!packs.length && <p className="muted">No seed packs available.</p>}
          </div>
        </section>

        <section className="card detail-pane">
          <div className="card-header">
            <h3>Pack detail</h3>
            {selected && (
              <div className="inline-actions">
                <button
                  className="ghost sm"
                  type="button"
                  onClick={() => void runApply({ pack_slugs: [selected.slug], dry_run: true }, "Dry run pack")}
                  disabled={!!actionBusy}
                >
                  Dry run
                </button>
                <button
                  className="primary sm"
                  type="button"
                  onClick={() => void runApply({ pack_slugs: [selected.slug] }, "Apply pack")}
                  disabled={!!actionBusy}
                >
                  Apply
                </button>
              </div>
            )}
          </div>
          {!selected && <p className="muted">Select a seed pack.</p>}
          {selected && (
            <div className="stack">
              <p className="muted">{selected.description || "No description."}</p>
              <div className="inline-metadata-row">
                <span className="meta-pill">Scope: {selected.scope}</span>
                <span className="meta-pill">Version: {selected.version}</span>
                <span className="meta-pill">Last applied: {selected.last_applied || "Never"}</span>
                <span className="meta-pill">Status: {selected.last_status || "n/a"}</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Entity</th>
                      <th>Status</th>
                      <th>Key</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(selected.items || []).map((item) => (
                      <tr key={item.id}>
                        <td>{item.entity_slug}</td>
                        <td>{item.status}</td>
                        <td>{JSON.stringify(item.entity_unique_key_json || {})}</td>
                      </tr>
                    ))}
                    {!selected.items?.length && (
                      <tr>
                        <td colSpan={3} className="muted">No items to display.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
