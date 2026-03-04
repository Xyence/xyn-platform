import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { clearStoredToken, consumeTokenFromLocation, getStoredToken } from "../auth/session";

type Device = { id: string; name: string };

export default function DeviceList() {
  const navigate = useNavigate();
  const [devices, setDevices] = useState<Device[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [newName, setNewName] = useState("");
  const [token, setToken] = useState<string>(getStoredToken());
  const [authReady, setAuthReady] = useState(false);
  const isAdmin = roles.includes("admin");

  const fetchMe = useCallback(async () => {
    if (!token) return;
    const response = await fetch("/api/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) return;
    const payload = await response.json();
    setRoles(payload?.roles ?? []);
  }, [token]);

  const fetchDevices = useCallback(async () => {
    if (!token) return;
    const response = await fetch("/api/devices", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) return;
    const payload = await response.json();
    setDevices(Array.isArray(payload) ? payload : []);
  }, [token]);

  const createDevice = useCallback(async () => {
    if (!token || !newName) return;
    const response = await fetch("/api/devices", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name: newName }),
    });
    if (!response.ok) return;
    setNewName("");
    fetchDevices();
  }, [token, newName, fetchDevices]);

  const deleteDevice = useCallback(
    async (id: string) => {
      if (!token) return;
      const response = await fetch(`/api/devices/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) return;
      fetchDevices();
    },
    [token, fetchDevices]
  );

  useEffect(() => {
    let cancelled = false;
    const ensureAuth = async () => {
      const hydrated = consumeTokenFromLocation();
      const stored = hydrated || getStoredToken();
      if (!stored) {
        clearStoredToken();
        if (!cancelled) navigate("/", { replace: true });
        return;
      }
      setToken(stored);
      try {
        const response = await fetch("/api/me", {
          headers: { Authorization: `Bearer ${stored}` },
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

  useEffect(() => {
    if (!authReady) {
      return;
    }
    fetchMe();
    fetchDevices();
  }, [authReady, fetchMe, fetchDevices]);

  if (!authReady) {
    return (
      <section>
        <h2>Checking session...</h2>
      </section>
    );
  }

  return (
    <section>
      <h2>Devices</h2>
      <p>Signed in via OIDC.</p>
      <button type="button" onClick={fetchDevices}>
        Refresh
      </button>
      <button
        type="button"
        onClick={() => {
          clearStoredToken();
          navigate("/", { replace: true });
        }}
      >
        Sign out
      </button>
      <ul>
        {devices.map((device) => (
          <li key={device.id}>
            {device.name}
            {isAdmin ? (
              <button type="button" onClick={() => deleteDevice(device.id)}>
                Delete
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {isAdmin ? (
        <div>
          <input
            type="text"
            placeholder="Device name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
          />
          <button type="button" onClick={createDevice}>
            Create device
          </button>
        </div>
      ) : (
        <p>Viewer role: create/delete disabled.</p>
      )}
      <Link to="/reports">View Reports</Link>
    </section>
  );
}
