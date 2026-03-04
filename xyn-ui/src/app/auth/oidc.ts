import { clearStoredIdToken, resolveApiBaseUrl, setStoredIdToken } from "../../api/client";

const OIDC_ISSUER = (import.meta.env.VITE_OIDC_ISSUER as string | undefined) || "https://accounts.google.com";
const OIDC_CLIENT_ID = (import.meta.env.VITE_OIDC_CLIENT_ID as string | undefined) || "";
const OIDC_REDIRECT_URI =
  (import.meta.env.VITE_OIDC_REDIRECT_URI as string | undefined) ||
  `${window.location.origin}/app/auth/callback`;
const OIDC_SCOPES = "openid profile email";

const STATE_KEY = "xyn_oidc_state";
const VERIFIER_KEY = "xyn_oidc_verifier";
const REDIRECT_KEY = "xyn_oidc_post_login";

export function isOidcConfigured() {
  return Boolean(OIDC_CLIENT_ID);
}

export async function startLogin(returnTo: string) {
  if (!OIDC_CLIENT_ID) return;
  const config = await getConfig();
  const state = crypto.randomUUID();
  const verifier = generateVerifier();
  const challenge = await generateChallenge(verifier);
  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(REDIRECT_KEY, returnTo);
  const params = new URLSearchParams({
    client_id: OIDC_CLIENT_ID,
    redirect_uri: OIDC_REDIRECT_URI,
    response_type: "code",
    scope: OIDC_SCOPES,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
    prompt: "select_account",
  });
  window.location.href = `${config.authorization_endpoint}?${params.toString()}`;
}

export async function handleCallback() {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const expected = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!code || !state || !expected || state !== expected || !verifier) {
    throw new Error("Invalid login response.");
  }
  const tokenResponse = await fetch(`${resolveApiBaseUrl()}/xyn/api/auth/oidc/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code,
      code_verifier: verifier,
      redirect_uri: OIDC_REDIRECT_URI,
    }),
  });
  if (!tokenResponse.ok) {
    throw new Error(await tokenResponse.text());
  }
  const payload = await tokenResponse.json();
  if (!payload.id_token) {
    throw new Error("Missing id_token.");
  }
  setStoredIdToken(payload.id_token);
  sessionStorage.removeItem(STATE_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  const redirectTo = sessionStorage.getItem(REDIRECT_KEY) || "/app/blueprints";
  sessionStorage.removeItem(REDIRECT_KEY);
  window.location.replace(redirectTo);
}

export async function logout() {
  clearStoredIdToken();
  const endSession = await getEndSessionEndpoint();
  const redirect = `${window.location.origin}/app`;
  if (endSession) {
    const params = new URLSearchParams({ post_logout_redirect_uri: redirect });
    window.location.href = `${endSession}?${params.toString()}`;
    return;
  }
  window.location.replace(redirect);
}

async function getEndSessionEndpoint(): Promise<string | null> {
  try {
    const config = await getConfig();
    return config.end_session_endpoint || null;
  } catch {
    return null;
  }
}

async function getConfig(): Promise<{
  authorization_endpoint: string;
  token_endpoint: string;
  end_session_endpoint?: string;
}> {
  const cached = sessionStorage.getItem("xyn_oidc_config");
  if (cached) {
    return JSON.parse(cached);
  }
  const response = await fetch(`${OIDC_ISSUER}/.well-known/openid-configuration`);
  if (!response.ok) {
    throw new Error("Failed to load OIDC configuration.");
  }
  const data = await response.json();
  const config = {
    authorization_endpoint: data.authorization_endpoint,
    token_endpoint: data.token_endpoint,
    end_session_endpoint: data.end_session_endpoint,
  };
  sessionStorage.setItem("xyn_oidc_config", JSON.stringify(config));
  return config;
}

function generateVerifier() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return base64UrlEncode(array);
}

async function generateChallenge(verifier: string) {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(digest));
}

function base64UrlEncode(buffer: Uint8Array) {
  return btoa(String.fromCharCode(...buffer))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
