const STATUS_COLOR: Record<string, string> = {
  requested: "status-neutral",
  provisioning: "status-warn",
  running: "status-info",
  ready: "status-good",
  error: "status-bad",
  terminating: "status-warn",
  terminated: "status-neutral",
  pending: "status-warn",
  succeeded: "status-good",
  failed: "status-bad",
  planned: "status-info",
  applied: "status-good",
};

export default function StatusPill({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? "status-neutral";
  return <span className={`status-pill ${color}`}>{status}</span>;
}
