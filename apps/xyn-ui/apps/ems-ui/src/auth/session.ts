const TOKEN_KEY = "ems_oidc_id_token";

export function getStoredToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function readIdTokenFromSearch(search: string): string {
  const value = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(value);
  return params.get("id_token") ?? "";
}

export function readIdTokenFromHash(hash: string): string {
  const value = hash.startsWith("#") ? hash.slice(1) : hash;
  const params = new URLSearchParams(value);
  return params.get("id_token") ?? "";
}

export function consumeTokenFromLocation(): string {
  const fromHash = readIdTokenFromHash(window.location.hash);
  const fromSearch = readIdTokenFromSearch(window.location.search);
  const token = fromHash || fromSearch;
  if (!token) {
    return "";
  }
  setStoredToken(token);
  const cleanPath = window.location.pathname;
  window.history.replaceState({}, "", cleanPath);
  return token;
}
