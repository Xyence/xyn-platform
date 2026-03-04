export type AtlasNode = "design" | "shape" | "package" | "run" | "observe";

type AtlasFlowProps = {
  current: AtlasNode;
};

const FLOW: Array<{ id: AtlasNode; label: string; detail: string }> = [
  { id: "design", label: "Design", detail: "Blueprints, Modules" },
  { id: "shape", label: "Shape", detail: "Drafts" },
  { id: "package", label: "Package", detail: "Releases, Plans" },
  { id: "run", label: "Run", detail: "Instances, Deploy" },
  { id: "observe", label: "Observe", detail: "Logs, Artifacts" },
];

export default function AtlasFlow({ current }: AtlasFlowProps) {
  return (
    <div className="atlas-flow" aria-label="Atlas flow">
      {FLOW.map((node, index) => (
        <div key={node.id} className={`atlas-node ${node.id === current ? "active" : ""}`}>
          <div className="atlas-node-label">{node.label}</div>
          <div className="atlas-node-detail">{node.detail}</div>
          {index < FLOW.length - 1 && <div className="atlas-link" aria-hidden="true" />}
        </div>
      ))}
    </div>
  );
}
