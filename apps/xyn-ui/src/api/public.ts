import { authHeaders, resolveApiBaseUrl } from "./client";
import type {
  Page,
  PublicArticleDetail,
  PublicArticlesResponse,
  PublicHomeResponse,
  PublicMenuResponse,
  PublicPageSectionsResponse,
  PublicPagesResponse,
  PublicSiteResponse,
} from "../public/types";

async function handle<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function fetchPublicMenu(): Promise<PublicMenuResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/xyn/api/public/menu`);
  return handle<PublicMenuResponse>(response);
}

export async function fetchPublicPages(): Promise<PublicPagesResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/xyn/api/public/pages`);
  return handle<PublicPagesResponse>(response);
}

export async function fetchPublicPageSections(slug: string): Promise<PublicPageSectionsResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/xyn/api/public/pages/${slug}/sections`);
  return handle<PublicPageSectionsResponse>(response);
}

export async function fetchPublicPage(slug: string): Promise<Page> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/xyn/api/public/pages/${slug}`);
  return handle<Page>(response);
}

export async function fetchPublicHome(): Promise<PublicHomeResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/xyn/api/public/home`);
  return handle<PublicHomeResponse>(response);
}

export async function fetchPublicSite(): Promise<PublicSiteResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/xyn/api/public/site`);
  return handle<PublicSiteResponse>(response);
}

export async function fetchPublicArticles(page = 1, surfacePath = "/articles"): Promise<PublicArticlesResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/public/articles`);
  url.searchParams.set("page", String(page));
  url.searchParams.set("surface_path", surfacePath);
  const response = await fetch(url.toString());
  return handle<PublicArticlesResponse>(response);
}

export async function fetchPublicArticle(slug: string, surfacePath = "/articles"): Promise<PublicArticleDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/public/articles/${slug}`);
  url.searchParams.set("surface_path", surfacePath);
  const response = await fetch(url.toString());
  return handle<PublicArticleDetail>(response);
}

export async function checkAuthenticated(): Promise<boolean> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/xyn/api/auth/session-check`, {
    credentials: "include",
    headers: { ...authHeaders() },
    redirect: "manual",
  });
  if (response.status === 0 || response.status === 302 || response.status === 307 || response.status === 308) {
    return false;
  }
  return response.ok;
}
