import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({
  breaks: true,
});

export function renderMarkdown(content?: string | null): string {
  if (!content) return "";
  const html = marked.parse(content) as string;
  return DOMPurify.sanitize(html);
}
