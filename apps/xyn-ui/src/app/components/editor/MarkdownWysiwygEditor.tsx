import { useCallback, useEffect, useMemo, useRef } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import type { Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";
import { renderMarkdown } from "../../../public/markdown";

export type EditorSelectionPayload = {
  selectedText: string;
  contextBefore: string;
  contextAfter: string;
  anchorRect?: {
    top: number;
    left: number;
    width: number;
    height: number;
  };
} | null;

type MarkdownWysiwygEditorProps = {
  value: string;
  onChange: (value: string) => void;
  onSelectionChange?: (selection: EditorSelectionPayload) => void;
  ariaLabel?: string;
  placeholder?: string;
  focusSignal?: number;
};

const CONTEXT_RADIUS = 600;

function normalizeMarkdown(value: string): string {
  return value.replace(/\r\n/g, "\n").trimEnd();
}

export default function MarkdownWysiwygEditor({
  value,
  onChange,
  onSelectionChange,
  ariaLabel = "Article editor",
  placeholder = "Start writing...",
  focusSignal = 0,
}: MarkdownWysiwygEditorProps) {
  const lastMarkdownRef = useRef(normalizeMarkdown(value));

  const turndownService = useMemo(() => {
    const service = new TurndownService({
      headingStyle: "atx",
      codeBlockStyle: "fenced",
      bulletListMarker: "-",
      emDelimiter: "_",
      strongDelimiter: "**",
    });
    service.use(gfm);
    return service;
  }, []);

  const toMarkdown = useCallback(
    (html: string): string => {
      if (!html) return "";
      return turndownService.turndown(html).trimEnd();
    },
    [turndownService]
  );

  const emitSelection = useCallback(
    (editorInstance: Editor) => {
      if (!onSelectionChange) return;
      const { from, to } = editorInstance.state.selection;
      if (to <= from) {
        onSelectionChange(null);
        return;
      }
      const selectedText = editorInstance.state.doc.textBetween(from, to, "\n\n", " ");
      if (!selectedText.trim()) {
        onSelectionChange(null);
        return;
      }
      const before = editorInstance.state.doc.textBetween(0, from, "\n\n", " ");
      const after = editorInstance.state.doc.textBetween(to, editorInstance.state.doc.content.size, "\n\n", " ");
      const domSelection = window.getSelection();
      const range = domSelection && domSelection.rangeCount > 0 ? domSelection.getRangeAt(0) : null;
      const rect = range ? range.getBoundingClientRect() : null;
      onSelectionChange({
        selectedText,
        contextBefore: before.slice(-CONTEXT_RADIUS),
        contextAfter: after.slice(0, CONTEXT_RADIUS),
        anchorRect:
          rect && Number.isFinite(rect.top)
            ? {
                top: rect.top,
                left: rect.left,
                width: rect.width,
                height: rect.height,
              }
            : undefined,
      });
    },
    [onSelectionChange]
  );

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3],
        },
      }),
      Placeholder.configure({
        placeholder,
      }),
    ],
    content: value ? renderMarkdown(value) : "<p></p>",
    editorProps: {
      attributes: {
        class: "article-wysiwyg-content",
        "aria-label": ariaLabel,
      },
    },
    onUpdate: ({ editor: editorInstance }) => {
      const next = normalizeMarkdown(toMarkdown(editorInstance.getHTML()));
      lastMarkdownRef.current = next;
      onChange(next);
      emitSelection(editorInstance);
    },
    onSelectionUpdate: ({ editor: editorInstance }) => {
      emitSelection(editorInstance);
    },
    onBlur: ({ editor: editorInstance }) => {
      emitSelection(editorInstance);
    },
  });

  useEffect(() => {
    if (!editor) return;
    const incoming = normalizeMarkdown(value);
    if (incoming === lastMarkdownRef.current) return;
    const current = normalizeMarkdown(toMarkdown(editor.getHTML()));
    if (current === incoming) {
      lastMarkdownRef.current = incoming;
      return;
    }
    editor.commands.setContent(incoming ? renderMarkdown(incoming) : "<p></p>", { emitUpdate: false });
    lastMarkdownRef.current = incoming;
    onSelectionChange?.(null);
  }, [editor, onSelectionChange, toMarkdown, value]);

  useEffect(() => {
    if (!editor) return;
    editor.commands.focus();
  }, [editor, focusSignal]);

  const buttonClass = "ghost sm editor-tool-button";

  return (
    <div className="article-wysiwyg">
      <div className="article-wysiwyg-toolbar" role="toolbar" aria-label="Formatting options">
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("heading", { level: 2 }) ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
          aria-pressed={Boolean(editor?.isActive("heading", { level: 2 }))}
        >
          H2
        </button>
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("heading", { level: 3 }) ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()}
          aria-pressed={Boolean(editor?.isActive("heading", { level: 3 }))}
        >
          H3
        </button>
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("bulletList") ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleBulletList().run()}
          aria-pressed={Boolean(editor?.isActive("bulletList"))}
        >
          Bullets
        </button>
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("orderedList") ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleOrderedList().run()}
          aria-pressed={Boolean(editor?.isActive("orderedList"))}
        >
          Numbered
        </button>
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("blockquote") ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleBlockquote().run()}
          aria-pressed={Boolean(editor?.isActive("blockquote"))}
        >
          Quote
        </button>
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("codeBlock") ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleCodeBlock().run()}
          aria-pressed={Boolean(editor?.isActive("codeBlock"))}
        >
          Code
        </button>
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("bold") ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleBold().run()}
          aria-pressed={Boolean(editor?.isActive("bold"))}
        >
          Bold
        </button>
        <button
          type="button"
          className={`${buttonClass} ${editor?.isActive("italic") ? "active" : ""}`}
          onClick={() => editor?.chain().focus().toggleItalic().run()}
          aria-pressed={Boolean(editor?.isActive("italic"))}
        >
          Italic
        </button>
        <button type="button" className={buttonClass} onClick={() => editor?.chain().focus().undo().run()} disabled={!editor?.can().undo()}>
          Undo
        </button>
        <button type="button" className={buttonClass} onClick={() => editor?.chain().focus().redo().run()} disabled={!editor?.can().redo()}>
          Redo
        </button>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}
