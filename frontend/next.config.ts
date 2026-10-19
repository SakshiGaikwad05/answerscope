import { networkInterfaces } from "node:os";

import type { NextConfig } from "next";

// The browser always calls the API on the frontend's own origin (/api/...), and
// Next proxies it to the backend. That works whether the app is opened via
// localhost, the WSL/LAN "Network" address or a hostname, with no CORS setup.
const BACKEND_URL = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

// In development Next only serves its scripts to localhost. Without this, opening
// the app via the "Network" URL that `next dev` prints leaves the page
// non-interactive (forms do nothing). Allow this machine's own private
// addresses, plus any extra hostnames listed in DEV_ALLOWED_ORIGINS.
function localDevOrigins(): string[] {
  const addresses = Object.values(networkInterfaces())
    .flat()
    .filter((i): i is NonNullable<typeof i> => Boolean(i && i.family === "IPv4" && !i.internal))
    .map((i) => i.address);
  const extra = (process.env.DEV_ALLOWED_ORIGINS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return [...new Set([...addresses, ...extra])];
}

const nextConfig: NextConfig = {
  /* config options here */
  // Self-contained server bundle for the production Docker image.
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  allowedDevOrigins: localDevOrigins(),
  experimental: {
    // AI fix drafts can take up to ~2 minutes; the /api proxy's default timeout is 30s.
    proxyTimeout: 150_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
