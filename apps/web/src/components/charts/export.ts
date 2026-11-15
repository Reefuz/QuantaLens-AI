import type { ChartSpec } from "@/lib/analyst";

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "chart";
}

/** Spreadsheet programs run text that starts with = + - @ as a formula. Prefix those cells so exports stay inert. */
export function csvCell(value: unknown): string {
  let s = value === null || value === undefined ? "" : Array.isArray(value) ? value.join(" ") : String(value);
  if (/^[=+\-@\t\r]/.test(s) && !/^-?\d+(\.\d+)?$/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(columns: string[], rows: unknown[][]): string {
  return [columns.map(csvCell).join(","), ...rows.map((r) => r.map(csvCell).join(","))].join("\r\n");
}

export function exportChartCsv(spec: ChartSpec) {
  const keys = Array.from(new Set(spec.data.flatMap((d) => Object.keys(d))));
  const csv = toCsv(keys, spec.data.map((d) => keys.map((k) => d[k] ?? "")));
  download(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }), `${slug(spec.title)}.csv`);
}

/** Render the chart's SVG to a PNG. Colours defined by CSS variables are resolved first, because a detached SVG cannot see the page's CSS. */
export async function exportChartPng(container: HTMLElement, title: string) {
  const svg = container.querySelector("svg");
  if (!svg) return;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const srcNodes = [svg, ...Array.from(svg.querySelectorAll("*"))];
  const dstNodes = [clone, ...Array.from(clone.querySelectorAll("*"))];
  srcNodes.forEach((src, i) => {
    const cs = getComputedStyle(src);
    const dst = dstNodes[i] as SVGElement;
    for (const prop of ["fill", "stroke", "stroke-width", "opacity", "font-family", "font-size", "font-weight", "text-anchor"]) {
      dst.style.setProperty(prop, cs.getPropertyValue(prop));
    }
  });
  const box = svg.getBoundingClientRect();
  const scale = 2;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(box.width));
  clone.setAttribute("height", String(box.height));
  const xml = new XMLSerializer().serializeToString(clone);
  const img = new Image();
  const bg = getComputedStyle(container.closest("[data-chart-card]") ?? document.body).backgroundColor;
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error("render failed"));
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  });
  const canvas = document.createElement("canvas");
  canvas.width = box.width * scale;
  canvas.height = (box.height + 44) * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(scale, scale);
  ctx.fillStyle = bg && bg !== "rgba(0, 0, 0, 0)" ? bg : "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = getComputedStyle(container).color || "#111";
  ctx.font = "600 15px system-ui, sans-serif";
  ctx.fillText(title, 12, 24);
  ctx.drawImage(img, 0, 44, box.width, box.height);
  canvas.toBlob((blob) => blob && download(blob, `${slug(title)}.png`), "image/png");
}
