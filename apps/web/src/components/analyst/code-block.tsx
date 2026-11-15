"use client";

import { useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const SQL_KEYWORDS = new Set(
  `select from where group by order having limit offset with as and or not in is null like ilike between case when then else end join left right inner outer full cross on using union all distinct asc desc over partition filter within cast exists any true false interval extract`.split(" "),
);
const PY_KEYWORDS = new Set(
  `import from as def return if elif else for while in not and or is lambda with try except finally raise pass break continue True False None print`.split(" "),
);

type Tok = { text: string; kind: "kw" | "str" | "num" | "com" | "fn" | "plain" };

/** A small tokenizer: enough to make SQL and Python readable without a syntax-highlighting dependency. */
export function tokenize(code: string, lang: "sql" | "python"): Tok[] {
  const kws = lang === "sql" ? SQL_KEYWORDS : PY_KEYWORDS;
  const toks: Tok[] = [];
  const re = lang === "sql"
    ? /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^']|'')*')|("(?:[^"]|"")*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)(\s*\()?|(\s+|.)/g
    : /(#[^\n]*)|('''[\s\S]*?'''|"""[\s\S]*?"""|'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*")|()(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)(\s*\()?|(\s+|.)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(code))) {
    if (m[1]) toks.push({ text: m[1], kind: "com" });
    else if (m[2]) toks.push({ text: m[2], kind: "str" });
    else if (lang === "sql" && m[3]) toks.push({ text: m[3], kind: "plain" });
    else if (m[4]) toks.push({ text: m[4], kind: "num" });
    else if (m[5]) {
      const word = m[5];
      const isKw = kws.has(lang === "sql" ? word.toLowerCase() : word);
      toks.push({ text: word, kind: isKw ? "kw" : m[6] ? "fn" : "plain" });
      if (m[6]) toks.push({ text: m[6], kind: "plain" });
    } else toks.push({ text: m[7] ?? m[0], kind: "plain" });
  }
  return toks;
}

const COLORS: Record<Tok["kind"], string> = {
  kw: "text-brand font-medium",
  str: "text-success",
  num: "text-warning",
  com: "text-muted-foreground italic",
  fn: "text-chart-2",
  plain: "",
};

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      variant="ghost"
      size="xs"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      {done ? <Check /> : <Copy />}
      {done ? "Copied" : label}
    </Button>
  );
}

export function CodeBlock({ code, lang, title, className, actions }: { code: string; lang: "sql" | "python"; title?: string; className?: string; actions?: ReactNode }) {
  const toks = tokenize(code, lang);
  return (
    <div className={cn("overflow-hidden rounded-md border bg-card", className)}>
      <div className="flex items-center justify-between border-b bg-muted/50 px-3 py-1">
        <span className="text-[11px] font-medium text-muted-foreground uppercase">{title ?? lang}</span>
        <div className="flex items-center gap-1">
          {actions}
          <CopyButton text={code} />
        </div>
      </div>
      <pre className="max-h-80 overflow-auto p-3 font-mono text-[12px] leading-relaxed break-words whitespace-pre-wrap">
        <code>
          {toks.map((t, i) => (
            <span key={i} className={COLORS[t.kind]}>
              {t.text}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
