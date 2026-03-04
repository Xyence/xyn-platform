import mermaid from "mermaid";

let initialized = false;

async function ensureMermaidInitialized() {
  if (initialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "default",
  });
  initialized = true;
}

function collectMermaidNodes(container: HTMLElement): HTMLElement[] {
  const targets: HTMLElement[] = [];

  const codeBlocks = Array.from(
    container.querySelectorAll(
      "pre > code.language-mermaid, pre > code.mermaid, code.language-mermaid, code.mermaid"
    )
  ) as HTMLElement[];

  for (const code of codeBlocks) {
    const host = document.createElement("div");
    host.className = "mermaid";
    host.textContent = code.textContent ?? "";

    const pre = code.closest("pre");
    if (pre) {
      pre.replaceWith(host);
    } else {
      code.replaceWith(host);
    }

    targets.push(host);
  }

  const existing = Array.from(container.querySelectorAll<HTMLElement>(".mermaid"));

  for (const node of existing) {
    if (!node.getAttribute("data-processed")) {
      targets.push(node);
    }
  }

  return Array.from(new Set(targets));
}

export async function renderMermaidIn(container: HTMLElement | null) {
  if (!container) return;
  await ensureMermaidInitialized();

  const targets = collectMermaidNodes(container);
  if (targets.length === 0) return;

  const nodeList = container.querySelectorAll<HTMLElement>(".mermaid");

  try {
    await mermaid.run({ nodes: nodeList });
  } catch (error) {
    try {
      mermaid.init(undefined, nodeList);
    } catch (fallbackError) {
      console.warn("Mermaid rendering failed.", error, fallbackError);
    }
  }
}
