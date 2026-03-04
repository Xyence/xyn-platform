export type MenuItem = {
  label: string;
  path: string;
  kind: "page" | "articles_index" | "external" | "route";
  requires_auth: boolean;
  page_slug?: string | null;
  external_url?: string | null;
  order?: number;
};

export type Page = {
  title: string;
  slug: string;
};

export type WebSection = {
  key: string;
  section_type:
    | "hero"
    | "feature_grid"
    | "service_cards"
    | "cta_band"
    | "quote"
    | "simple_md";
  title?: string | null;
  body_md?: string;
  data_json?: Record<string, unknown> | null;
  order?: number;
};

export type PublicMenuResponse = {
  items: MenuItem[];
};

export type PublicPagesResponse = {
  items: Page[];
};

export type PublicPageSectionsResponse = {
  items: WebSection[];
};

export type PublicHomeResponse = {
  menu: MenuItem[];
  page: Page | null;
  sections: WebSection[];
};

export type PublicSiteResponse = {
  site_name: string;
};

export type PublicArticleSummary = {
  title: string;
  slug: string;
  summary?: string;
  published_at?: string;
  updated_at?: string;
};

export type PublicArticlesResponse = {
  items: PublicArticleSummary[];
  count?: number;
  next?: number | null;
  prev?: number | null;
};

export type PublicArticleDetail = {
  title: string;
  slug: string;
  summary?: string;
  published_at?: string;
  updated_at?: string;
  body_html?: string;
  body_markdown?: string;
  body_md?: string;
  excerpt?: string;
};
