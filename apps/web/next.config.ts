import type { NextConfig } from "next";

// Server-side only. Never prefix with NEXT_PUBLIC.
const ENGINE_URL = (process.env.PYTHON_ANALYTICS_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const isProd = process.env.NODE_ENV === "production";
// Next injects inline scripts for hydration, so script-src needs 'unsafe-inline' without a nonce setup. Everything else is locked down.
const CSP = ["default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:", "font-src 'self' data:", "connect-src 'self'", "worker-src 'self' blob:", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"].join("; ");

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Gzip would buffer the streamed analysis events (NDJSON) that the rewrite proxies from the engine.
  // On Vercel, compression happens at the edge and does not affect streaming.
  compress: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    // The browser only talks to this origin, so the session cookie is first-party.
    return [{ source: "/api/:path*", destination: `${ENGINE_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          ...(isProd ? [{ key: "Content-Security-Policy", value: CSP }, { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }] : []),
        ],
      },
    ];
  },
};

export default nextConfig;
