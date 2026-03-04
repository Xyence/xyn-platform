import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { consumeTokenFromLocation, readIdTokenFromHash, setStoredToken } from "./session";

export default function Callback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string>("");

  useEffect(() => {
    const token = consumeTokenFromLocation() || readIdTokenFromHash(window.location.hash);
    if (!token) {
      setError("OIDC callback did not include an id_token.");
      return;
    }
    setStoredToken(token);
    navigate("/devices", { replace: true });
  }, [navigate]);

  if (error) {
    return (
      <section>
        <h2>Sign in failed</h2>
        <p>{error}</p>
      </section>
    );
  }

  return (
    <section>
      <h2>Signing you in...</h2>
    </section>
  );
}
