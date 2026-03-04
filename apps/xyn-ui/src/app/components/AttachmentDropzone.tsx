import { useCallback, useEffect, useRef, useState } from "react";

type Props = {
  files: File[];
  onChange: (files: File[]) => void;
};

function mergeFiles(current: File[], incoming: File[]): File[] {
  const dedup = new Map<string, File>();
  for (const file of [...current, ...incoming]) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    dedup.set(key, file);
  }
  return Array.from(dedup.values());
}

export default function AttachmentDropzone({ files, onChange }: Props) {
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const addFiles = useCallback(
    (incoming: File[]) => {
      if (!incoming.length) return;
      onChange(mergeFiles(files, incoming));
    },
    [files, onChange]
  );

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (!event.clipboardData) return;
      const pasted: File[] = [];
      for (const item of Array.from(event.clipboardData.items)) {
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) pasted.push(file);
        }
      }
      if (pasted.length > 0) {
        event.preventDefault();
        addFiles(pasted);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [addFiles]);

  return (
    <div className="stack">
      <div
        className={`dropzone ${dragActive ? "active" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setDragActive(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          const dropped = Array.from(event.dataTransfer.files || []);
          addFiles(dropped);
        }}
      >
        <strong>Drag/drop images here, or paste from clipboard</strong>
        <div className="muted small">PNG/JPG recommended. Multiple attachments supported.</div>
        <div className="inline-actions">
          <button className="ghost" type="button" onClick={() => inputRef.current?.click()}>
            Add files
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept="image/*"
            style={{ display: "none" }}
            onChange={(event) => addFiles(Array.from(event.target.files || []))}
          />
        </div>
      </div>
      {files.length > 0 && (
        <div className="instance-list">
          {files.map((file, idx) => (
            <div className="item-row" key={`${file.name}:${file.size}:${idx}`}>
              <div>
                <strong>{file.name}</strong>
                <div className="muted small">
                  {file.type || "application/octet-stream"} · {file.size} bytes
                </div>
              </div>
              <button
                className="danger"
                type="button"
                onClick={() => onChange(files.filter((_f, i) => i !== idx))}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
