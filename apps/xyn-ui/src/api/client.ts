import type {
  BootstrapLogResponse,
  CreateInstancePayload,
  InstanceContainersResponse,
  InstanceListResponse,
  ProvisionedInstance,
} from "./types";

export function resolveApiBaseUrl() {
  const envBase = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (envBase && envBase.trim().length > 0) {
    return envBase;
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://localhost:8000";
}

export function resolveSeedBaseUrl() {
  const envBase = import.meta.env.VITE_SEED_API_URL as string | undefined;
  if (envBase && envBase.trim().length > 0) {
    return envBase.replace(/\/+$/, "");
  }
  return "http://localhost:8001";
}

export const authMode =
  (import.meta.env.VITE_AUTH_MODE as string | undefined) || "token";

const ID_TOKEN_KEY = "xyn_id_token";

export function getStoredIdToken(): string | null {
  if (typeof window === "undefined") return null;
  const token = window.localStorage.getItem(ID_TOKEN_KEY);
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1] || ""));
    if (payload?.exp && Date.now() / 1000 > payload.exp) {
      window.localStorage.removeItem(ID_TOKEN_KEY);
      return null;
    }
  } catch {
    return null;
  }
  return token;
}

export function setStoredIdToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ID_TOKEN_KEY, token);
}

export function clearStoredIdToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(ID_TOKEN_KEY);
}

export function authHeaders(): Record<string, string> {
  if (authMode !== "token") {
    return {};
  }
  const runtimeToken = getStoredIdToken();
  if (runtimeToken) {
    return { Authorization: `Bearer ${runtimeToken}` };
  }
  const token = import.meta.env.VITE_API_TOKEN as string | undefined;
  if (token && token.trim().length > 0) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

const jsonHeaders = {
  "Content-Type": "application/json",
};

function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = { ...authHeaders(), ...(init.headers || {}) } as Record<string, string>;
  return fetch(input, { ...init, headers });
}

function htmlAuthErrorMessage(response: Response, body: string): string {
  const url = (response.url || "").toLowerCase();
  const text = (body || "").toLowerCase();
  if (
    response.status === 401 ||
    response.status === 403 ||
    url.includes("/auth/login") ||
    url.includes("/accounts/login") ||
    url.includes("/admin/login") ||
    text.includes("login")
  ) {
    return "Not authenticated. Please sign in.";
  }
  if (response.status >= 500) {
    return `Server error (${response.status}). Please try again.`;
  }
  return `Unexpected HTML response (${response.status}).`;
}

async function handle<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    const message = await response.text();
    if (message.includes("<!DOCTYPE") || message.includes("<html")) {
      throw new Error(htmlAuthErrorMessage(response, message));
    }
    throw new Error(message || `Request failed (${response.status})`);
  }
  if (response.status === 204) {
    return {} as T;
  }
  if (!contentType.includes("application/json")) {
    const message = await response.text();
    if (message.includes("<!DOCTYPE") || message.includes("<html")) {
      throw new Error(htmlAuthErrorMessage(response, message));
    }
    throw new Error(message || "Unexpected response format.");
  }
  return (await response.json()) as T;
}

export async function listInstances(environmentId?: string): Promise<InstanceListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/provision/instances`);
  if (environmentId) {
    url.searchParams.set("environment_id", environmentId);
  }
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: { ...authHeaders() },
  });
  return handle<InstanceListResponse>(response);
}

export async function createInstance(payload: CreateInstancePayload): Promise<ProvisionedInstance> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/provision/instances`, {
    method: "POST",
    headers: { ...jsonHeaders, ...authHeaders() },
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<ProvisionedInstance>(response);
}

export async function getInstance(id: string, refresh = false): Promise<ProvisionedInstance> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/provision/instances/${id}`);
  if (refresh) {
    url.searchParams.set("refresh", "true");
  }
  const response = await apiFetch(url.toString(), { credentials: "include", headers: { ...authHeaders() } });
  return handle<ProvisionedInstance>(response);
}

export async function updateInstance(
  id: string,
  payload: { environment_id: string; force?: boolean }
): Promise<ProvisionedInstance> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/provision/instances/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { ...jsonHeaders, ...authHeaders() },
    body: JSON.stringify(payload),
  });
  return handle<ProvisionedInstance>(response);
}

export async function destroyInstance(id: string): Promise<ProvisionedInstance> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/provision/instances/${id}/destroy`, {
    method: "POST",
    credentials: "include",
    headers: { ...authHeaders() },
  });
  return handle<ProvisionedInstance>(response);
}

export async function retryProvisionInstance(id: string): Promise<ProvisionedInstance> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/provision/instances/${id}/retry`, {
    method: "POST",
    credentials: "include",
    headers: { ...authHeaders() },
  });
  return handle<ProvisionedInstance>(response);
}

export async function fetchBootstrapLog(id: string, tail = 200): Promise<BootstrapLogResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/provision/instances/${id}/bootstrap-log`);
  url.searchParams.set("tail", String(tail));
  const response = await apiFetch(url.toString(), { credentials: "include", headers: { ...authHeaders() } });
  return handle<BootstrapLogResponse>(response);
}

export async function fetchInstanceContainers(id: string): Promise<InstanceContainersResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/provision/instances/${id}/containers`, {
    credentials: "include",
    headers: { ...authHeaders() },
  });
  return handle<InstanceContainersResponse>(response);
}

export async function fetchArtifactJson<T = unknown>(url: string): Promise<T> {
  const apiBaseUrl = resolveApiBaseUrl();
  const target = url.startsWith("http") ? url : `${apiBaseUrl}${url}`;
  const response = await apiFetch(target, { credentials: "include", headers: { ...authHeaders() } });
  return handle<T>(response);
}
