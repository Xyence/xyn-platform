import { useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { handleCallback } from "../auth/oidc";

export default function AuthCallbackPage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        await handleCallback();
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  return (
    <div className="page-header">
      <div>
        <h2>Signing in...</h2>
        <p className="muted">Completing authentication flow.</p>
      </div>
      {error && <InlineMessage tone="error" title="Login failed" body={error} />}
    </div>
  );
}
