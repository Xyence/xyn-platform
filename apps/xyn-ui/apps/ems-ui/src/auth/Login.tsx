import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { clearStoredToken, consumeTokenFromLocation, getStoredToken } from "./session";

type OidcConfig = {
  app_id?: string;
  auth_base_url?: string;
};

const DEFAULT_APP_ID = "ems.platform";
const DEFAULT_AUTH_BASE = "https://xyence.io";

export default function Login() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<"ok" | "down" | "checking">("checking");
  const [authStatus, setAuthStatus] = useState<"unknown" | "signed_out" | "signed_in">("unknown");
  const [meResult, setMeResult] = useState<string>("");
  const [meIdentity, setMeIdentity] = useState<string>("");
  const [oidcConfig, setOidcConfig] = useState<OidcConfig | null>(null);
  const hasAutoRedirected = useRef(false);
  const meLabel = useMemo(() => (meResult ? "Response:" : "Response will appear here."), [meResult]);

  const checkHealth = useCallback(async () => {
    setStatus("checking");
    try {
      const response = await fetch("/api/health");
      if (!response.ok) {
        setStatus("down");
        return;
      }
      const payload = (await response.json()) as { status?: string };
      setStatus(payload.status === "ok" ? "ok" : "down");
    } catch {
      setStatus("down");
    }
  }, []);

  const callMe = useCallback(async () => {
    setMeResult("");
    setMeIdentity("");
    const token = getStoredToken();
    if (!token) {
      setAuthStatus("signed_out");
      setMeResult("Not signed in.");
      return;
    }
    try {
      const response = await fetch("/api/me", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        setAuthStatus("signed_out");
        if (response.status === 401 || response.status === 403) {
          clearStoredToken();
        }
        setMeResult(`Unauthorized (${response.status})`);
        return;
      }
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        clearStoredToken();
        setAuthStatus("signed_out");
        const snippet = (await response.text()).slice(0, 140);
        setMeResult(`Request failed: expected JSON from /api/me; received ${contentType || "unknown"}: ${snippet}`);
        return;
      }
      const payload = await response.json();
      if (payload?.user?.email) {
        setMeIdentity(`Logged in as ${payload.user.email}`);
      } else if (payload?.user?.subject) {
        setMeIdentity(`Logged in as ${payload.user.subject}`);
      }
      setMeResult(JSON.stringify(payload, null, 2));
      setAuthStatus("signed_in");
    } catch (err) {
      clearStoredToken();
      setAuthStatus("signed_out");
      setMeResult(`Request failed: ${String(err)}`);
    }
  }, []);

  const signOut = useCallback(async () => {
    clearStoredToken();
    setAuthStatus("signed_out");
    setMeIdentity("");
    setMeResult("");
  }, []);

  const loadOidcConfig = useCallback(async () => {
    try {
      const response = await fetch("/api/auth/oidc/config");
      if (!response.ok) {
        setOidcConfig({ app_id: DEFAULT_APP_ID, auth_base_url: DEFAULT_AUTH_BASE });
        return;
      }
      const payload = (await response.json()) as OidcConfig;
      setOidcConfig({
        app_id: payload.app_id || DEFAULT_APP_ID,
        auth_base_url: payload.auth_base_url || DEFAULT_AUTH_BASE,
      });
    } catch (err) {
      setOidcConfig({ app_id: DEFAULT_APP_ID, auth_base_url: DEFAULT_AUTH_BASE });
    }
  }, []);

  const startLogin = useCallback(() => {
    const authBase = (oidcConfig?.auth_base_url || DEFAULT_AUTH_BASE).replace(/\/$/, "");
    const appId = oidcConfig?.app_id || DEFAULT_APP_ID;
    const returnTo = `${window.location.origin}/auth/callback`;
    window.location.href = `${authBase}/auth/login?appId=${encodeURIComponent(appId)}&returnTo=${encodeURIComponent(returnTo)}`;
  }, [oidcConfig]);

  useEffect(() => {
    consumeTokenFromLocation();
    checkHealth();
    loadOidcConfig();
    callMe();
  }, [checkHealth, loadOidcConfig, callMe]);

  useEffect(() => {
    if (authStatus !== "signed_out" || !oidcConfig || hasAutoRedirected.current) {
      return;
    }
    hasAutoRedirected.current = true;
    startLogin();
  }, [authStatus, oidcConfig, startLogin]);

  useEffect(() => {
    if (authStatus === "signed_in") {
      navigate("/devices", { replace: true });
    }
  }, [authStatus, navigate]);

  return (
    <section>
      <h2>Sign in</h2>
      <p>Use your corporate account to sign in.</p>
      <p>API: {status === "ok" ? "OK" : status === "down" ? "DOWN" : "CHECKING"}</p>
      <button type="button" onClick={checkHealth}>
        Retry
      </button>
      <div>
        {authStatus !== "signed_in" ? (
          <button type="button" onClick={startLogin}>
            Sign in
          </button>
        ) : (
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        )}
        <button type="button" onClick={callMe}>
          Refresh session
        </button>
      </div>
      {meIdentity ? <p>{meIdentity}</p> : null}
      <pre>{meLabel}{meResult ? `\n${meResult}` : ""}</pre>
      <Link to="/devices">Continue to Devices</Link>
    </section>
  );
}
