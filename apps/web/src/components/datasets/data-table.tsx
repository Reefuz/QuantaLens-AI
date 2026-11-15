"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Loader2, Plus, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { getRows, type RowFilter, type RowsPage } from "@/lib/datasets";
import { cn } from "@/lib/utils";

type Row = RowsPage["rows"][number];
const PAGE_SIZES = [25, 50, 100];
const NUMERIC = new Set(["bigint", "double precision", "date", "timestamp"]);

const TEXT_OPS = [
  ["contains", "contains"],
  ["equals", "equals"],
  ["is_null", "is empty"],
  ["not_null", "is not empty"],
] as const;
const ORDERED_OPS = [
  ["equals", "equals"],
  ["gt", "greater than"],
  ["gte", "at least"],
  ["lt", "less than"],
  ["lte", "at most"],
  ["is_null", "is empty"],
  ["not_null", "is not empty"],
] as const;
const OP_LABEL: Record<string, string> = Object.fromEntries([...TEXT_OPS, ...ORDERED_OPS]);

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function Cell({ value }: { value: Row[string] }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground/70 italic">NULL</span>;
  if (typeof value === "boolean") return <>{String(value)}</>;
  return <span className="whitespace-pre">{String(value)}</span>;
}

export function DataTable({ datasetId, version }: { datasetId: string; version: "original" | "cleaned" }) {
  const [page, setPage] = useState<RowsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [searchText, setSearchText] = useState("");
  const [filters, setFilters] = useState<RowFilter[]>([]);
  const [draft, setDraft] = useState<{ column: string; op: string; value: string } | null>(null);
  const search = useDebounced(searchText, 300);
  const latest = useRef(0);
  const columnsRef = useRef<RowsPage["columns"]>([]);

  // Reset paging whenever the query changes.
  useEffect(() => setPageIndex(0), [search, filters, sorting, pageSize, version]);

  useEffect(() => {
    const id = ++latest.current;
    setLoading(true);
    getRows(datasetId, {
      version,
      offset: pageIndex * pageSize,
      limit: pageSize,
      sort: sorting[0]?.id,
      desc: sorting[0]?.desc,
      search: search.trim() || undefined,
      filters,
    })
      .then((p) => {
        if (id !== latest.current) return; // a newer request superseded this one
        columnsRef.current = p.columns;
        setPage(p);
        setError(null);
      })
      .catch((e) => id === latest.current && setError(e instanceof ApiError ? e.message : "Could not load rows."))
      .finally(() => id === latest.current && setLoading(false));
  }, [datasetId, version, pageIndex, pageSize, sorting, search, filters]);

  const columns = useMemo<ColumnDef<Row>[]>(() => {
    const cols = page?.columns ?? columnsRef.current;
    return [
      {
        id: "_row_id",
        header: "#",
        accessorKey: "_row_id",
        enableSorting: false,
        cell: (c) => <span className="text-muted-foreground tabular-nums">{String(c.getValue())}</span>,
      },
      ...cols.map<ColumnDef<Row>>((c) => ({
        id: c.name,
        accessorKey: c.name,
        header: c.original_name,
        meta: { numeric: NUMERIC.has(c.db_type), type: c.db_type },
        cell: (ctx) => <Cell value={ctx.getValue() as Row[string]} />,
      })),
    ];
  }, [page?.columns]);

  const table = useReactTable({
    data: page?.rows ?? [],
    columns,
    state: { sorting },
    manualSorting: true,
    manualPagination: true,
    enableMultiSort: false,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
  });

  const total = page?.total ?? 0;
  const from = total === 0 ? 0 : pageIndex * pageSize + 1;
  const to = Math.min(total, (pageIndex + 1) * pageSize);
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
  const dataColumns = page?.columns ?? [];
  const draftType = dataColumns.find((c) => c.name === draft?.column)?.db_type ?? "text";
  const ops = NUMERIC.has(draftType) ? ORDERED_OPS : TEXT_OPS;
  const needsValue = draft && draft.op !== "is_null" && draft.op !== "not_null";

  function addFilter() {
    if (!draft) return;
    if (needsValue && draft.value.trim() === "") return;
    setFilters((f) => [...f, { column: draft.column, op: draft.op, ...(needsValue ? { value: draft.value } : {}) }]);
    setDraft(null);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={searchText} onChange={(e) => setSearchText(e.target.value)} placeholder="Search all columns" aria-label="Search all columns" className="pl-8" />
        </div>
        <Button variant="outline" onClick={() => setDraft(draft ? null : { column: dataColumns[0]?.name ?? "", op: "contains", value: "" })}>
          <Plus /> Filter
        </Button>
        {filters.map((f, i) => (
          <span key={i} className="inline-flex items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-xs">
            <span className="font-medium">{dataColumns.find((c) => c.name === f.column)?.original_name ?? f.column}</span>
            <span className="text-muted-foreground">{OP_LABEL[f.op] ?? f.op}</span>
            {f.value !== undefined && <span>{f.value}</span>}
            <button type="button" aria-label="Remove filter" onClick={() => setFilters((fs) => fs.filter((_, j) => j !== i))}>
              <X className="size-3" />
            </button>
          </span>
        ))}
        {loading && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Loading" />}
      </div>

      {draft && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3">
          <select
            aria-label="Filter column"
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={draft.column}
            onChange={(e) => setDraft({ column: e.target.value, op: "contains", value: "" })}
          >
            {dataColumns.map((c) => (
              <option key={c.name} value={c.name}>
                {c.original_name}
              </option>
            ))}
          </select>
          <select aria-label="Filter operator" className="h-8 rounded-md border bg-background px-2 text-sm" value={draft.op} onChange={(e) => setDraft({ ...draft, op: e.target.value })}>
            {ops.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          {needsValue && (
            <Input
              aria-label="Filter value"
              className="w-44"
              value={draft.value}
              onChange={(e) => setDraft({ ...draft, value: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && addFilter()}
              placeholder={draftType === "date" ? "YYYY-MM-DD" : "Value"}
              autoFocus
            />
          )}
          <Button onClick={addFilter}>Apply</Button>
          <Button variant="ghost" onClick={() => setDraft(null)}>
            Cancel
          </Button>
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      <div className={cn("max-h-[65vh] overflow-auto rounded-lg border bg-card transition-opacity", loading && page && "opacity-60")}>
        <table className="w-full min-w-max text-sm">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sorted = h.column.getIsSorted();
                  const numeric = (h.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric;
                  return (
                    <th key={h.id} className={cn("border-b px-3 py-2 text-left text-xs font-medium whitespace-nowrap text-muted-foreground", numeric && "text-right")} aria-sort={sorted ? (sorted === "asc" ? "ascending" : "descending") : "none"}>
                      {h.column.getCanSort() ? (
                        <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => h.column.toggleSorting(sorted === "asc", false)}
                          onDoubleClick={() => h.column.clearSorting()}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {sorted === "asc" && <ArrowUp className="size-3" />}
                          {sorted === "desc" && <ArrowDown className="size-3" />}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y">
            {table.getRowModel().rows.map((r) => (
              <tr key={r.id} className="hover:bg-accent/40">
                {r.getVisibleCells().map((c) => {
                  const numeric = (c.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric;
                  return (
                    <td key={c.id} className={cn("px-3 py-1.5 whitespace-nowrap", numeric && "text-right tabular-nums")}>
                      {flexRender(c.column.columnDef.cell, c.getContext())}
                    </td>
                  );
                })}
              </tr>
            ))}
            {page && page.rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10 text-center text-sm text-muted-foreground">
                  {search || filters.length ? "No rows match your search or filters." : "This dataset has no rows."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
        <span className="tabular-nums">
          {from.toLocaleString("en-GB")}–{to.toLocaleString("en-GB")} of {total.toLocaleString("en-GB")} rows
        </span>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs">
            Rows per page
            <select className="h-7 rounded-md border bg-background px-1.5 text-sm text-foreground" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
              {PAGE_SIZES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={pageIndex === 0 || loading} onClick={() => setPageIndex((p) => Math.max(0, p - 1))}>
            <ChevronLeft />
          </Button>
          <span className="min-w-16 text-center text-xs tabular-nums">
            Page {pageIndex + 1} / {lastPage + 1}
          </span>
          <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={pageIndex >= lastPage || loading} onClick={() => setPageIndex((p) => Math.min(lastPage, p + 1))}>
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
