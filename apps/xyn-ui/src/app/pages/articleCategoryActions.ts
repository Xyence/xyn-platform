export type CategoryActionView = {
  canDeletePermanently: boolean;
  showDeprecate: boolean;
  showReenable: boolean;
  helperText: string | null;
};

export function resolveCategoryActions(input: {
  enabled: boolean;
  referencedArticleCount: number;
}): CategoryActionView {
  const count = Number(input.referencedArticleCount || 0);
  if (count > 0) {
    return {
      canDeletePermanently: false,
      showDeprecate: Boolean(input.enabled),
      showReenable: !input.enabled,
      helperText: `This category is referenced by ${count} article${count === 1 ? "" : "s"} and cannot be deleted. Deprecate it to prevent future use.`,
    };
  }
  return {
    canDeletePermanently: true,
    showDeprecate: Boolean(input.enabled),
    showReenable: !input.enabled,
    helperText: null,
  };
}
