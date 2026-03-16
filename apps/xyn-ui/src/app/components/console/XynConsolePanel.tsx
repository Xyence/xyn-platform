import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useXynConsole } from "../../state/xynConsoleStore";
import XynConsoleCore from "./XynConsoleCore";

export default function XynConsolePanel() {
  const { open, setOpen, pendingCloseBlock, openPanel } = useXynConsole();
  const location = useLocation();
  const navigate = useNavigate();
  const panelRef = useRef<HTMLElement | null>(null);
  const mobileHistoryEntryRef = useRef(false);
  const ignoreNextPopRef = useRef(false);
  const mediaQuery = "(max-width: 768px)";
  const readMobileViewport = () =>
    typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(mediaQuery).matches : false;
  const [mobileViewport, setMobileViewport] = useState(() =>
    readMobileViewport()
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(mediaQuery);
    const onChange = () => setMobileViewport(media.matches);
    onChange();
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    }
    media.addListener(onChange);
    return () => media.removeListener(onChange);
  }, []);

  useEffect(() => {
    const onMouseDown = (event: MouseEvent) => {
      if (!open) return;
      if (pendingCloseBlock) return;
      const target = event.target as Node | null;
      if (target instanceof Element && target.closest(".xyn-console-anchor")) {
        return;
      }
      if (panelRef.current && !panelRef.current.contains(target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open, pendingCloseBlock, setOpen]);

  useEffect(() => {
    if (!mobileViewport) return;
    const onPopState = () => {
      if (ignoreNextPopRef.current) {
        ignoreNextPopRef.current = false;
        return;
      }
      if (open) {
        mobileHistoryEntryRef.current = false;
        setOpen(false);
      }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [mobileViewport, open, setOpen]);

  useEffect(() => {
    if (!mobileViewport) return;
    if (open && !mobileHistoryEntryRef.current) {
      window.history.pushState(
        { ...(window.history.state || {}), __xyn_palette: true },
        document.title
      );
      mobileHistoryEntryRef.current = true;
      return;
    }
    if (!open && mobileHistoryEntryRef.current) {
      ignoreNextPopRef.current = true;
      mobileHistoryEntryRef.current = false;
      window.history.back();
    }
  }, [mobileViewport, open]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;

  return (
    <section className="xyn-console-panel" ref={panelRef} role="dialog" aria-label="Xyn Console">
      <XynConsoleCore
        mode="overlay"
        onRequestClose={() => setOpen(false)}
        onOpenPanel={(panelKey, params) => {
          openPanel({ key: panelKey, params: params || {}, open_in: "new_panel" });
          setOpen(false);
          // Navigate to workbench so the new panel is actually visible.
          const onWorkbench = /\/w\/[^/]+\/workbench\/?$/.test(location.pathname);
          if (!onWorkbench) {
            const match = location.pathname.match(/^\/w\/([^/]+)(?:\/|$)/);
            const wsId = match?.[1] ? decodeURIComponent(match[1]) : "";
            if (wsId) {
              navigate(`/w/${encodeURIComponent(wsId)}/workbench`);
            }
          }
        }}
      />
    </section>
  );
}
