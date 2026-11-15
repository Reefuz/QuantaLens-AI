import Link from "next/link";
import {
  BarChart3,
  Braces,
  DatabaseZap,
  FileText,
  LockKeyhole,
  MessagesSquare,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function SectionHeading({ eyebrow, title, body }: { eyebrow: string; title: string; body?: string }) {
  return (
    <div className="mb-10 max-w-2xl">
      <p className="mb-3 text-sm font-medium text-brand">{eyebrow}</p>
      <h2 className="text-2xl font-semibold tracking-tight text-balance md:text-3xl">{title}</h2>
      {body && <p className="mt-3 leading-relaxed text-muted-foreground">{body}</p>}
    </div>
  );
}

const STEPS = [
  { icon: ScanSearch, title: "Upload and profile", body: "Drop in a CSV. QuantaLens reports missing values, duplicates, mixed types, inconsistent dates and outliers before you ask anything." },
  { icon: Wrench, title: "Review the fixes", body: "Each proposed correction comes with a preview. Nothing is applied until you approve it, and your original file is never modified." },
  { icon: MessagesSquare, title: "Ask in plain English", body: "The agent plans the analysis, then chooses between SQL, Python and charts as the question requires." },
  { icon: ShieldCheck, title: "Inspect and verify", body: "Read the exact SQL and Python that ran. Key figures are recalculated independently and marked verified or unverified." },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20 border-y bg-secondary/40">
      <div className="mx-auto max-w-6xl px-5 py-20">
        <SectionHeading eyebrow="How it works" title="From a messy file to a checked answer" />
        <ol className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="bg-card p-6">
              <div className="mb-4 flex items-center justify-between">
                <s.icon className="size-5 text-brand" />
                <span className="font-mono text-xs text-muted-foreground">0{i + 1}</span>
              </div>
              <h3 className="mb-2 text-[15px] font-semibold">{s.title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

const CAPABILITIES = [
  { icon: Braces, title: "Inspectable SQL and Python", body: "Every query and script is shown, copyable and reproducible." },
  { icon: BarChart3, title: "Charts from real results", body: "Bar, line, scatter, histogram, box plot and heatmap, chosen from the shape of the data." },
  { icon: Sparkles, title: "Multi-step analysis", body: "The agent can re-run or refine an analysis when the first result is not enough." },
  { icon: DatabaseZap, title: "CSV and PostgreSQL", body: "Analyse uploads or connect a read-only PostgreSQL database." },
  { icon: MessagesSquare, title: "Follow-up questions", body: "Conversations keep dataset context, so you can say “compare that with last quarter”." },
  { icon: FileText, title: "Exportable reports", body: "PDF, CSV and Excel exports built from the actual analytical output." },
];

export function Capabilities() {
  return (
    <section id="capabilities" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-20">
      <SectionHeading eyebrow="Capabilities" title="Built for analysts who need to show their working" />
      <div className="grid gap-x-10 gap-y-9 sm:grid-cols-2 lg:grid-cols-3">
        {CAPABILITIES.map((c) => (
          <div key={c.title}>
            <c.icon className="mb-3 size-5 text-muted-foreground" />
            <h3 className="mb-1.5 text-[15px] font-semibold">{c.title}</h3>
            <p className="text-sm leading-relaxed text-muted-foreground">{c.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

const EXAMPLE = [
  ["Question", "Compare month-on-month revenue by segment and flag unusual transactions."],
  ["Plan", "Aggregate by month and segment, calculate growth, run an outlier test on amounts."],
  ["Execution", "SQL for the aggregation. Python for growth rates and the outlier test."],
  ["Validation", "Segment totals reconciled to the overall total. Growth rates recalculated."],
  ["Answer", "Findings, evidence, risks and limitations, with observed facts kept apart from possible explanations."],
];

export function ExampleWorkflow() {
  return (
    <section className="border-t bg-secondary/40">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-20 lg:grid-cols-[1fr_1.4fr]">
        <SectionHeading
          eyebrow="Example workflow"
          title="One question, a traceable chain of steps"
          body="Each stage in the timeline maps to something the backend actually did. The interface does not show progress that did not happen."
        />
        <dl className="divide-y rounded-xl border bg-card">
          {EXAMPLE.map(([k, v]) => (
            <div key={k} className="grid gap-1 px-5 py-4 sm:grid-cols-[110px_1fr] sm:gap-4">
              <dt className="text-sm font-medium">{k}</dt>
              <dd className="text-sm text-muted-foreground">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

const SECURITY = [
  "Passwords hashed with Argon2. Sessions are revocable and stored server-side.",
  "Generated SQL is parsed and restricted to read-only queries on your own data.",
  "Analysis code runs in a restricted runner with time and memory limits, no network and no secrets.",
  "Dataset contents are treated as untrusted and cannot change the agent's instructions.",
  "External database credentials are encrypted at rest and never sent to the model.",
  "You can delete a dataset and everything derived from it.",
];

export function Security() {
  return (
    <section id="security" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-20">
      <SectionHeading
        eyebrow="Security and privacy"
        title="Designed so your data stays yours"
        body="Security shapes the architecture. The limits of each control are documented in the repository."
      />
      <ul className="grid gap-3 md:grid-cols-2">
        {SECURITY.map((s) => (
          <li key={s} className="flex items-start gap-3 rounded-lg border bg-card p-4 text-sm">
            <LockKeyhole className="mt-0.5 size-4 shrink-0 text-brand" />
            <span className="text-muted-foreground">{s}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CallToAction() {
  return (
    <section className="mx-auto max-w-6xl px-5 pb-24">
      <div className="rounded-xl border bg-card px-6 py-14 text-center">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">See what your data says.</h2>
        <p className="mx-auto mt-3 max-w-lg text-muted-foreground">
          Create an account and start with the synthetic banking dataset, or upload your own CSV.
        </p>
        <div className="mt-7 flex justify-center">
          <Link href="/register" className={cn(buttonVariants({ size: "lg" }), "h-10 px-4 text-sm")}>
            Start Analysing
          </Link>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <p>QuantaLens AI. See Beyond the Data.</p>
        <p>Sample data in this product is synthetic.</p>
      </div>
    </footer>
  );
}
