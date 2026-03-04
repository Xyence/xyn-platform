export type DiffOpType = "context" | "add" | "remove";

export type DiffOp = {
  type: DiffOpType;
  text: string;
};

export type DiffSummary = {
  added: number;
  removed: number;
  changed: number;
};

export type LineDiff = {
  ops: DiffOp[];
  summary: DiffSummary;
};

function splitLines(value: string): string[] {
  return String(value || "").replace(/\r\n/g, "\n").split("\n");
}

function lcsTable(left: string[], right: string[]): number[][] {
  const rows = left.length + 1;
  const cols = right.length + 1;
  const dp = Array.from({ length: rows }, () => Array(cols).fill(0));
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      if (left[i] === right[j]) dp[i][j] = dp[i + 1][j + 1] + 1;
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  return dp;
}

export function computeLineDiff(previousText: string, nextText: string): LineDiff {
  const left = splitLines(previousText);
  const right = splitLines(nextText);
  const table = lcsTable(left, right);
  const ops: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (left[i] === right[j]) {
      ops.push({ type: "context", text: left[i] });
      i += 1;
      j += 1;
      continue;
    }
    if (table[i + 1][j] >= table[i][j + 1]) {
      ops.push({ type: "remove", text: left[i] });
      i += 1;
    } else {
      ops.push({ type: "add", text: right[j] });
      j += 1;
    }
  }
  while (i < left.length) {
    ops.push({ type: "remove", text: left[i] });
    i += 1;
  }
  while (j < right.length) {
    ops.push({ type: "add", text: right[j] });
    j += 1;
  }

  let added = 0;
  let removed = 0;
  for (const op of ops) {
    if (op.type === "add") added += 1;
    if (op.type === "remove") removed += 1;
  }

  return {
    ops,
    summary: {
      added,
      removed,
      changed: added + removed,
    },
  };
}
