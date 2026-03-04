export default function CanvasEmpty({ message }: { message?: string }) {
  return <p className="muted">{message || "No data."}</p>;
}
