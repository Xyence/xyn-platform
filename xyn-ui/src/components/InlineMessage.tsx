type InlineMessageProps = {
  tone?: "info" | "warn" | "error";
  title: string;
  body?: string;
};

export default function InlineMessage({ tone = "info", title, body }: InlineMessageProps) {
  return (
    <div className={`inline-message inline-${tone}`}>
      <strong>{title}</strong>
      {body && <span>{body}</span>}
    </div>
  );
}
