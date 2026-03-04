import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";

type EditorCentricLayoutProps = {
  top: ReactNode;
  main: ReactNode;
  inspector: ReactNode;
  activity: ReactNode;
  stickyTop?: boolean;
};

const LAYOUT_WIDTHS_STORAGE_KEY = "xyn.editorCentricLayout.widths";
const DEFAULT_LEFT_WIDTH = 320;
const DEFAULT_RIGHT_WIDTH = 340;
const MIN_LEFT_WIDTH = 280;
const MAX_LEFT_WIDTH = 340;
const MIN_RIGHT_WIDTH = 320;
const MAX_RIGHT_WIDTH = 380;
const MIN_CENTER_WIDTH = 560;
const SPLITTER_TOTAL_WIDTH = 20;

type SplitterSide = "left" | "right";
type DragState = { side: SplitterSide; startX: number; startWidth: number } | null;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readStoredWidths(): { left: number; right: number } {
  if (typeof window === "undefined") {
    return { left: DEFAULT_LEFT_WIDTH, right: DEFAULT_RIGHT_WIDTH };
  }
  try {
    const raw = window.localStorage.getItem(LAYOUT_WIDTHS_STORAGE_KEY);
    if (!raw) return { left: DEFAULT_LEFT_WIDTH, right: DEFAULT_RIGHT_WIDTH };
    const parsed = JSON.parse(raw) as { left?: number; right?: number };
    return {
      left: clamp(Number(parsed.left) || DEFAULT_LEFT_WIDTH, MIN_LEFT_WIDTH, MAX_LEFT_WIDTH),
      right: clamp(Number(parsed.right) || DEFAULT_RIGHT_WIDTH, MIN_RIGHT_WIDTH, MAX_RIGHT_WIDTH),
    };
  } catch {
    return { left: DEFAULT_LEFT_WIDTH, right: DEFAULT_RIGHT_WIDTH };
  }
}

/**
 * Reusable editor-centric template.
 * Keep primary editor content centered while metadata and activity panels
 * remain accessible without forcing full-page vertical stacking.
 */
export default function EditorCentricLayout({ top, main, inspector, activity, stickyTop = true }: EditorCentricLayoutProps) {
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [leftWidth, setLeftWidth] = useState(() => readStoredWidths().left);
  const [rightWidth, setRightWidth] = useState(() => readStoredWidths().right);
  const [drag, setDrag] = useState<DragState>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(LAYOUT_WIDTHS_STORAGE_KEY, JSON.stringify({ left: leftWidth, right: rightWidth }));
  }, [leftWidth, rightWidth]);

  const onMouseDownSplitter = useCallback(
    (side: SplitterSide) => (event: ReactMouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      const startWidth = side === "left" ? leftWidth : rightWidth;
      setDrag({ side, startX: event.clientX, startWidth });
    },
    [leftWidth, rightWidth]
  );

  useEffect(() => {
    if (!drag) return;
    const onMouseMove = (event: MouseEvent) => {
      const gridWidth = gridRef.current?.getBoundingClientRect().width || 0;
      const maxLeftByCenter = gridWidth > 0 ? Math.max(MIN_LEFT_WIDTH, gridWidth - rightWidth - MIN_CENTER_WIDTH - SPLITTER_TOTAL_WIDTH) : MAX_LEFT_WIDTH;
      const maxRightByCenter = gridWidth > 0 ? Math.max(MIN_RIGHT_WIDTH, gridWidth - leftWidth - MIN_CENTER_WIDTH - SPLITTER_TOTAL_WIDTH) : MAX_RIGHT_WIDTH;
      const delta = event.clientX - drag.startX;
      if (drag.side === "left") {
        const next = clamp(drag.startWidth + delta, MIN_LEFT_WIDTH, Math.min(MAX_LEFT_WIDTH, maxLeftByCenter));
        setLeftWidth(next);
      } else {
        const next = clamp(drag.startWidth - delta, MIN_RIGHT_WIDTH, Math.min(MAX_RIGHT_WIDTH, maxRightByCenter));
        setRightWidth(next);
      }
    };
    const onMouseUp = () => setDrag(null);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    document.body.classList.add("editor-layout-resizing");
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      document.body.classList.remove("editor-layout-resizing");
    };
  }, [drag, leftWidth, rightWidth]);

  const gridStyle = useMemo(
    () =>
      ({
        "--editor-left-col": `${leftWidth}px`,
        "--editor-right-col": `${rightWidth}px`,
      }) as CSSProperties,
    [leftWidth, rightWidth]
  );

  return (
    <section className="editor-centric-layout">
      <div className={`editor-centric-top ${stickyTop ? "" : "is-static"}`.trim()}>{top}</div>
      <div className="editor-centric-grid" ref={gridRef} style={gridStyle}>
        <aside className="editor-centric-activity card">{activity}</aside>
        <button
          type="button"
          className="editor-centric-splitter editor-centric-splitter-left"
          aria-label="Resize left panel"
          onMouseDown={onMouseDownSplitter("left")}
        />
        <section className="editor-centric-main card">{main}</section>
        <button
          type="button"
          className="editor-centric-splitter editor-centric-splitter-right"
          aria-label="Resize right panel"
          onMouseDown={onMouseDownSplitter("right")}
        />
        <aside className="editor-centric-inspector card">{inspector}</aside>
      </div>
    </section>
  );
}
