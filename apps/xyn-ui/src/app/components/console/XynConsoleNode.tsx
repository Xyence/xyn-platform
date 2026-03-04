import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { useXynConsole } from "../../state/xynConsoleStore";
import XynConsolePanel from "./XynConsolePanel";

const XYN_PALETTE_USED_KEY = "xyn.palette.used.v1";

export default function XynConsoleNode() {
  const { open, setOpen, badgeActive } = useXynConsole();
  const [showHint, setShowHint] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(XYN_PALETTE_USED_KEY) !== "1";
  });

  useEffect(() => {
    if (!open) return;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(XYN_PALETTE_USED_KEY, "1");
    }
    setShowHint(false);
  }, [open]);

  return (
    <div className="xyn-console-anchor">
      {showHint ? <span className="xyn-console-hint">Press ⌘K</span> : null}
      <button
        type="button"
        className={`xyn-console-node ${open ? "open" : ""}`}
        onClick={() => setOpen(!open)}
        aria-label="Xyn (⌘K / Ctrl+K)"
        title="Xyn (⌘K / Ctrl+K)"
      >
        <Sparkles size={14} />
        <span>Xyn</span>
        {badgeActive ? <span className="xyn-console-badge" aria-hidden="true" /> : null}
      </button>
      <XynConsolePanel />
    </div>
  );
}
