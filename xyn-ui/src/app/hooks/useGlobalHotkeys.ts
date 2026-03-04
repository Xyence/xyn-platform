import { useEffect } from "react";

type HotkeyHandler = (event: KeyboardEvent) => void;

export function useGlobalHotkeys(handler: HotkeyHandler) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      handler(event);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handler]);
}
