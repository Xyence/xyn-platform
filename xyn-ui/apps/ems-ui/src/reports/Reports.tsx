import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import { clearStoredToken, getStoredToken } from "../auth/session";

export default function Reports() {
  const navigate = useNavigate();
  const [authReady, setAuthReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const ensureAuth = async () => {
      const token = getStoredToken();
      if (!token) {
        clearStoredToken();
        if (!cancelled) navigate("/", { replace: true });
        return;
      }
      try {
        const response = await fetch("/api/me", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) {
          clearStoredToken();
          if (!cancelled) navigate("/", { replace: true });
          return;
        }
      } catch {
        clearStoredToken();
        if (!cancelled) navigate("/", { replace: true });
        return;
      }
      if (!cancelled) {
        setAuthReady(true);
      }
    };
    ensureAuth();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  if (!authReady) {
    return (
      <section>
        <h2>Checking session...</h2>
      </section>
    );
  }

  return (
    <section>
      <h2>Reports</h2>
      <p>Report data will appear here.</p>
      <Link to="/devices">Back to Devices</Link>
    </section>
  );
}
