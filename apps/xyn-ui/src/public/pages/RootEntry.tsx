import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { checkAuthenticated, fetchPublicRootResolution } from "../../api/public";
import HomePage from "./HomePage";

type RootTarget = "public" | "open-console" | "login";

export default function RootEntry() {
  const [target, setTarget] = useState<RootTarget | "">("");

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const resolution = await fetchPublicRootResolution();
        if (!mounted) return;
        if (resolution.mode === "public") {
          setTarget("public");
          return;
        }
      } catch {
        // Fail closed into private/auth-first behavior.
      }

      try {
        const authed = await checkAuthenticated();
        if (!mounted) return;
        setTarget(authed ? "open-console" : "login");
      } catch {
        if (!mounted) return;
        setTarget("login");
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  if (!target) return <p className="muted">Loading...</p>;
  if (target === "public") return <HomePage />;
  if (target === "open-console") return <Navigate to="/open-console" replace />;
  if (typeof window !== "undefined") {
    const loginUrl = `/auth/login?appId=xyn-ui&returnTo=${encodeURIComponent("/open-console")}`;
    window.location.replace(loginUrl);
  }
  return null;
}
