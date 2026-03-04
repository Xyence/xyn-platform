import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import {
  createArticle,
  createArticleCategory,
  createCategoryBinding,
  deleteArticleCategory,
  deleteCategoryBinding,
  listArticleCategories,
  listArticles,
  listCategoryBindings,
  updateArticleCategory,
} from "../../api/xyn";
import type { ArticleCategoryRecord, ArticleFormat, ArticleSummary, PublishBindingRecord } from "../../api/types";
import { resolveCategoryActions } from "./articleCategoryActions";
import { useNotifications } from "../state/notificationsStore";

type CategoryForm = {
  slug: string;
  name: string;
  description: string;
  enabled: boolean;
};

export default function ArtifactsArticlesPage({
  workspaceId,
  canCreate,
}: {
  workspaceId: string;
  canCreate: boolean;
}) {
  const navigate = useNavigate();
  const { push } = useNotifications();
  const createButtonRef = useRef<HTMLButtonElement | null>(null);
  const createTitleInputRef = useRef<HTMLInputElement | null>(null);
  const listRowRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  const [tab, setTab] = useState<"articles" | "categories">("articles");
  const [items, setItems] = useState<ArticleSummary[]>([]);
  const [categories, setCategories] = useState<ArticleCategoryRecord[]>([]);
  const [bindings, setBindings] = useState<PublishBindingRecord[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createTitle, setCreateTitle] = useState("");
  const [createCategorySlug, setCreateCategorySlug] = useState("web");
  const [createArticleFormat, setCreateArticleFormat] = useState<ArticleFormat>("standard");
  const [createErrors, setCreateErrors] = useState<{ title?: string; category?: string; form?: string }>({});
  const [createLoading, setCreateLoading] = useState(false);
  const [highlightArticleId, setHighlightArticleId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [visibilityFilter, setVisibilityFilter] = useState("");
  const [includeDeprecated, setIncludeDeprecated] = useState(false);
  const [selectedCategorySlug, setSelectedCategorySlug] = useState("");
  const [categoryForm, setCategoryForm] = useState<CategoryForm>({ slug: "", name: "", description: "", enabled: true });
  const [bindingForm, setBindingForm] = useState({ label: "", target_type: "xyn_ui_route", target_value: "", enabled: true });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadArticles = useCallback(async () => {
    if (!workspaceId) {
      setItems([]);
      return;
    }
    const data = await listArticles({ workspace_id: workspaceId, include_unpublished: true });
    setItems(data.articles || []);
  }, [workspaceId]);

  const loadCategories = useCallback(async () => {
    const data = await listArticleCategories();
    const next = data.categories || [];
    setCategories(next);
    if (!selectedCategorySlug && next.length) {
      setSelectedCategorySlug(next[0].slug);
    }
  }, [selectedCategorySlug]);

  const loadBindings = useCallback(async () => {
    if (!selectedCategorySlug) {
      setBindings([]);
      return;
    }
    const data = await listCategoryBindings(selectedCategorySlug);
    setBindings(data.bindings || []);
  }, [selectedCategorySlug]);

  const loadAll = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      await Promise.all([loadArticles(), loadCategories()]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [loadArticles, loadCategories]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    loadBindings();
  }, [loadBindings]);

  const filtered = useMemo(() => {
    const search = q.trim().toLowerCase();
    return items.filter((item) => {
      if (!includeDeprecated && item.status === "deprecated") return false;
      if (categoryFilter && item.category !== categoryFilter) return false;
      if (visibilityFilter && item.visibility_type !== visibilityFilter) return false;
      if (!search) return true;
      const haystack = `${item.title} ${item.slug || ""} ${item.summary || ""} ${(item.tags || []).join(" ")}`.toLowerCase();
      return haystack.includes(search);
    });
  }, [categoryFilter, includeDeprecated, items, q, visibilityFilter]);

  const categoryOptions = useMemo(() => {
    const options = categories.filter((item) => item.enabled).map((item) => item.slug);
    if (!options.includes("web")) options.unshift("web");
    return options;
  }, [categories]);

  const visibilityOptions = useMemo(
    () => Array.from(new Set(items.map((item) => item.visibility_type).filter(Boolean))).sort(),
    [items]
  );

  const filteredCategoryOptions = useMemo(
    () => Array.from(new Set(items.map((item) => item.category).filter(Boolean))).sort(),
    [items]
  );

  const selectedCategory = useMemo(
    () => categories.find((item) => item.slug === selectedCategorySlug) || null,
    [categories, selectedCategorySlug]
  );
  const selectedCategoryActions = resolveCategoryActions({
    enabled: Boolean(selectedCategory?.enabled),
    referencedArticleCount: Number(selectedCategory?.referenced_article_count || selectedCategory?.references?.articles || 0),
  });

  const openCreateModal = useCallback(() => {
    const storedCategory = window.localStorage.getItem("xyn.articles.lastCategory") || "";
    const storedFormat = window.localStorage.getItem("xyn.articles.lastCreateAs") as ArticleFormat | null;
    const nextCategory = storedCategory && categoryOptions.includes(storedCategory) ? storedCategory : (categoryOptions[0] || "web");
    const nextFormat = storedFormat === "video_explainer" ? "video_explainer" : "standard";
    setCreateTitle("");
    setCreateCategorySlug(nextCategory);
    setCreateArticleFormat(nextFormat);
    setCreateErrors({});
    setShowCreateModal(true);
  }, [categoryOptions]);

  const closeCreateModal = useCallback(() => {
    setShowCreateModal(false);
    window.setTimeout(() => createButtonRef.current?.focus(), 0);
  }, []);

  const createDraft = async () => {
    const trimmedTitle = createTitle.trim();
    const nextErrors: { title?: string; category?: string } = {};
    if (!trimmedTitle) nextErrors.title = "Title is required.";
    if (!createCategorySlug.trim()) nextErrors.category = "Category is required.";
    if (nextErrors.title || nextErrors.category) {
      setCreateErrors(nextErrors);
      return;
    }
    try {
      setCreateLoading(true);
      setError(null);
      setCreateErrors({});
      const response = await createArticle({
        workspace_id: workspaceId,
        title: trimmedTitle,
        category: createCategorySlug,
        visibility_type: "private",
        body_markdown: "",
        format: createArticleFormat,
      });
      const createdArticleId = response?.article?.id;
      window.localStorage.setItem("xyn.articles.lastCategory", createCategorySlug);
      window.localStorage.setItem("xyn.articles.lastCreateAs", createArticleFormat);
      closeCreateModal();
      if (createdArticleId) {
        navigate(`/app/artifacts/${createdArticleId}`);
        return;
      }
      await loadArticles();
      const fallbackId = response?.article?.id || null;
      if (fallbackId) {
        setHighlightArticleId(fallbackId);
        window.setTimeout(() => {
          listRowRefs.current[fallbackId]?.scrollIntoView({ behavior: "smooth", block: "center" });
          listRowRefs.current[fallbackId]?.focus();
        }, 40);
        window.setTimeout(() => setHighlightArticleId((prev) => (prev === fallbackId ? null : prev)), 2000);
      }
      push({
        level: "success",
        title: "Draft created",
        message: "Open the new draft to continue editing.",
        href: fallbackId ? `/app/artifacts/${fallbackId}` : undefined,
        ctaLabel: fallbackId ? "Continue editing" : undefined,
      });
    } catch (err) {
      const message = (err as Error).message || "Could not create draft.";
      setCreateErrors({ form: message });
      push({ level: "error", title: "Create draft failed", message });
    } finally {
      setCreateLoading(false);
    }
  };

  useEffect(() => {
    if (!showCreateModal) return;
    const focusTimer = window.setTimeout(() => createTitleInputRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !createLoading) {
        event.preventDefault();
        closeCreateModal();
      }
      if (event.key !== "Tab") return;
      const modal = document.querySelector(".articles-create-modal");
      if (!(modal instanceof HTMLElement)) return;
      const focusable = Array.from(
        modal.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((element) => !element.hasAttribute("hidden") && element.tabIndex !== -1);
      if (focusable.length < 2) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [closeCreateModal, createLoading, showCreateModal]);

  const createCategory = async () => {
    try {
      setError(null);
      if (!categoryForm.slug.trim() || !categoryForm.name.trim()) {
        setError("Category slug and name are required.");
        return;
      }
      await createArticleCategory({ ...categoryForm, slug: categoryForm.slug.trim().toLowerCase() });
      setCategoryForm({ slug: "", name: "", description: "", enabled: true });
      setMessage("Category created.");
      await loadCategories();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const saveCategory = async () => {
    if (!selectedCategory) return;
    try {
      await updateArticleCategory(selectedCategory.slug, {
        name: selectedCategory.name,
        description: selectedCategory.description,
        enabled: selectedCategory.enabled,
      });
      setMessage("Category updated.");
      await loadCategories();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const removeCategory = async () => {
    if (!selectedCategory) return;
    try {
      const confirmed = window.confirm("This category has never been used. Deleting it will permanently remove it.");
      if (!confirmed) return;
      await deleteArticleCategory(selectedCategory.slug);
      setMessage("Category deleted.");
      setSelectedCategorySlug("");
      await loadCategories();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const addBinding = async () => {
    if (!selectedCategory) return;
    try {
      await createCategoryBinding(selectedCategory.slug, {
        label: bindingForm.label,
        target_type: bindingForm.target_type,
        target_value: bindingForm.target_value,
        enabled: bindingForm.enabled,
      });
      setBindingForm({ label: "", target_type: "xyn_ui_route", target_value: "", enabled: true });
      await loadBindings();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Articles</h2>
          <p className="muted">Governed article artifacts in this workspace.</p>
        </div>
        <div className="inline-actions">
          {tab === "articles" && canCreate && (
            <button ref={createButtonRef} className="primary" onClick={openCreateModal}>
              New Article
            </button>
          )}
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Articles" body={message} />}

      <div className="page-tabs">
        <Tabs
          ariaLabel="Articles workspace tabs"
          value={tab}
          onChange={setTab}
          options={[
            { value: "articles", label: "Articles" },
            { value: "categories", label: "Categories" },
          ]}
        />
      </div>

      {tab === "articles" && (
        <>
          <section className="article-filter-bar" aria-label="Article filters">
            <div className="article-filter-row">
              <label className="article-filter-field article-filter-search">
                <span className="sr-only">Search articles</span>
                <input className="input" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search title, slug, summary, tags" />
              </label>
              <label className="article-filter-field">
                <span className="sr-only">Filter by category</span>
                <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                  <option value="">All categories</option>
                  {filteredCategoryOptions.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="article-filter-field">
                <span className="sr-only">Filter by visibility</span>
                <select value={visibilityFilter} onChange={(event) => setVisibilityFilter(event.target.value)}>
                  <option value="">All visibility</option>
                  {visibilityOptions.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="checkbox-row compact">
                <input type="checkbox" checked={includeDeprecated} onChange={(event) => setIncludeDeprecated(event.target.checked)} />
                <span>Include deprecated</span>
              </label>
            </div>
          </section>
          <section className="card">
            <div className="card-header">
              <h3>Articles</h3>
            </div>
            <div className="instance-list">
              {filtered.map((item) => (
                <Link
                  className={`instance-row article-row ${highlightArticleId === item.id ? "flash" : ""}`}
                  key={item.id}
                  to={`/app/artifacts/${item.id}`}
                  ref={(element) => {
                    listRowRefs.current[item.id] = element;
                  }}
                >
                  <div>
                    <strong>{item.title}</strong>
                    <span className="muted small article-row-meta">
                      {item.slug || item.id} · {item.category} · {item.visibility_type}
                    </span>
                  </div>
                  <div className="muted small">{item.status}</div>
                </Link>
              ))}
              {filtered.length === 0 && <p className="muted">No articles matched your filters.</p>}
            </div>
          </section>
        </>
      )}

      {tab === "categories" && (
        <div className="two-col-layout">
          <section className="card">
            <div className="card-header">
              <h3>Category Index</h3>
            </div>
            <div className="stack">
              {categories.map((category) => (
                <button
                  key={category.id}
                  type="button"
                  className={`instance-row ${selectedCategorySlug === category.slug ? "active" : ""}`}
                  onClick={() => setSelectedCategorySlug(category.slug)}
                >
                  <strong>{category.name}</strong>
                  <span className="muted small">
                    {category.slug} · {category.enabled ? "enabled" : "deprecated"} · refs {category.referenced_article_count ?? category.references?.articles ?? 0}
                  </span>
                </button>
              ))}
            </div>
            {canCreate && (
              <div className="stack" style={{ marginTop: 12 }}>
                <h4>Create category</h4>
                <label className="stacked-field">
                  <span>Slug</span>
                  <input className="input" value={categoryForm.slug} onChange={(event) => setCategoryForm({ ...categoryForm, slug: event.target.value })} />
                </label>
                <label className="stacked-field">
                  <span>Name</span>
                  <input className="input" value={categoryForm.name} onChange={(event) => setCategoryForm({ ...categoryForm, name: event.target.value })} />
                </label>
                <label className="stacked-field">
                  <span>Description</span>
                  <textarea className="input" rows={3} value={categoryForm.description} onChange={(event) => setCategoryForm({ ...categoryForm, description: event.target.value })} />
                </label>
                <label className="checkbox-inline">
                  <input type="checkbox" checked={categoryForm.enabled} onChange={(event) => setCategoryForm({ ...categoryForm, enabled: event.target.checked })} />
                  <span>Enabled</span>
                </label>
                <button className="primary" onClick={createCategory}>Create category</button>
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-header">
              <h3>{selectedCategory?.name || "Category"}</h3>
            </div>
            {selectedCategory ? (
              <>
                <div className="form-grid">
                  <label>
                    Slug
                    <input className="input" value={selectedCategory.slug} disabled />
                  </label>
                  <label>
                    Name
                    <input
                      className="input"
                      value={selectedCategory.name}
                      onChange={(event) =>
                        setCategories((prev) => prev.map((item) => (item.id === selectedCategory.id ? { ...item, name: event.target.value } : item)))
                      }
                    />
                  </label>
                  <label>
                    Description
                    <textarea
                      className="input"
                      rows={3}
                      value={selectedCategory.description || ""}
                      onChange={(event) =>
                        setCategories((prev) => prev.map((item) => (item.id === selectedCategory.id ? { ...item, description: event.target.value } : item)))
                      }
                    />
                  </label>
                  <label className="checkbox-inline">
                    <input
                      type="checkbox"
                      checked={selectedCategory.enabled}
                      onChange={(event) =>
                        setCategories((prev) => prev.map((item) => (item.id === selectedCategory.id ? { ...item, enabled: event.target.checked } : item)))
                      }
                    />
                    <span>Enabled</span>
                  </label>
                </div>
                <div className="inline-actions">
                  <button className="primary" onClick={saveCategory}>Save category</button>
                  {!selectedCategoryActions.canDeletePermanently && selectedCategoryActions.showDeprecate && (
                    <button
                      className="danger"
                      onClick={async () => {
                        if (!selectedCategory) return;
                        try {
                          await updateArticleCategory(selectedCategory.slug, { enabled: false });
                          setMessage("Category deprecated.");
                          await loadCategories();
                        } catch (err) {
                          setError((err as Error).message);
                        }
                      }}
                    >
                      Deprecate
                    </button>
                  )}
                  {selectedCategoryActions.showReenable && (
                    <button
                      className="ghost"
                      onClick={async () => {
                        if (!selectedCategory) return;
                        try {
                          await updateArticleCategory(selectedCategory.slug, { enabled: true });
                          setMessage("Category re-enabled.");
                          await loadCategories();
                        } catch (err) {
                          setError((err as Error).message);
                        }
                      }}
                    >
                      Re-enable
                    </button>
                  )}
                  {selectedCategoryActions.canDeletePermanently && (
                    <button className="danger" onClick={removeCategory}>Delete permanently</button>
                  )}
                </div>
                {selectedCategoryActions.helperText && <p className="muted small">{selectedCategoryActions.helperText}</p>}

                <div className="card-header" style={{ marginTop: 12 }}>
                  <h3>Bindings</h3>
                </div>
                <div className="instance-list">
                  {bindings.map((binding) => (
                    <div className="instance-row" key={binding.id}>
                      <div>
                        <strong>{binding.label}</strong>
                        <span className="muted small">{binding.target_type} · {binding.target_value} · {binding.enabled ? "enabled" : "disabled"}</span>
                      </div>
                      {canCreate && (
                        <button className="danger" onClick={async () => {
                          try {
                            await deleteCategoryBinding(selectedCategory.slug, binding.id);
                            await loadBindings();
                          } catch (err) {
                            setError((err as Error).message);
                          }
                        }}>
                          Delete
                        </button>
                      )}
                    </div>
                  ))}
                  {bindings.length === 0 && <p className="muted">No bindings for this category.</p>}
                </div>
                {canCreate && (
                  <div className="form-grid">
                    <label>
                      Label
                      <input className="input" value={bindingForm.label} onChange={(event) => setBindingForm({ ...bindingForm, label: event.target.value })} />
                    </label>
                    <label>
                      Target type
                      <select value={bindingForm.target_type} onChange={(event) => setBindingForm({ ...bindingForm, target_type: event.target.value })}>
                        <option value="xyn_ui_route">xyn_ui_route</option>
                        <option value="public_web_path">public_web_path</option>
                        <option value="external_url">external_url</option>
                      </select>
                    </label>
                    <label>
                      Target value
                      <input className="input" value={bindingForm.target_value} onChange={(event) => setBindingForm({ ...bindingForm, target_value: event.target.value })} />
                    </label>
                    <label className="checkbox-inline">
                      <input type="checkbox" checked={bindingForm.enabled} onChange={(event) => setBindingForm({ ...bindingForm, enabled: event.target.checked })} />
                      <span>Enabled</span>
                    </label>
                    <button className="primary" onClick={addBinding}>Add binding</button>
                  </div>
                )}
              </>
            ) : (
              <p className="muted">Select a category.</p>
            )}
          </section>
        </div>
      )}

      {showCreateModal && (
        <div className="modal-backdrop" onClick={createLoading ? undefined : closeCreateModal}>
          <div className="modal articles-create-modal" role="dialog" aria-modal="true" aria-labelledby="article-create-title" onClick={(event) => event.stopPropagation()}>
            <h3 id="article-create-title">New Article</h3>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault();
                if (!createLoading) createDraft();
              }}
            >
              <label>
                Title
                <input
                  ref={createTitleInputRef}
                  className="input"
                  value={createTitle}
                  onChange={(event) => setCreateTitle(event.target.value)}
                  aria-invalid={Boolean(createErrors.title)}
                />
                {createErrors.title && <span className="error-text">{createErrors.title}</span>}
              </label>
              <label>
                Category
                <select
                  value={createCategorySlug}
                  onChange={(event) => setCreateCategorySlug(event.target.value)}
                  aria-invalid={Boolean(createErrors.category)}
                >
                  <option value="">Select category</option>
                  {categoryOptions.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
                {createErrors.category && <span className="error-text">{createErrors.category}</span>}
              </label>
              <label>
                Create as
                <select value={createArticleFormat} onChange={(event) => setCreateArticleFormat(event.target.value as ArticleFormat)}>
                  <option value="standard">Standard Article</option>
                  <option value="video_explainer">Explainer Video</option>
                </select>
              </label>
              {createErrors.form && <p className="error-text" role="alert">{createErrors.form}</p>}
              <div className="inline-actions">
                <button className="primary" type="submit" disabled={createLoading}>
                  {createLoading ? "Creating..." : "Create draft"}
                </button>
                <button className="ghost" type="button" onClick={closeCreateModal} disabled={createLoading}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
