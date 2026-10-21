import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Runs before /api/* is forwarded to the backend (see rewrites in next.config.ts).
// - Passes the visitor's IP in a header the browser can't spoof, for the backend's rate limits.
// - Proves the request came through this frontend with a shared secret (BACKEND_PROXY_SECRET,
//   server-side only), so a publicly reachable backend can refuse direct calls.
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete("x-aeo-proxy-secret");
  headers.delete("x-aeo-client-ip");
  // Vercel and most hosts overwrite these with the real client address.
  const ip = request.headers.get("x-real-ip") || request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "";
  if (ip) headers.set("x-aeo-client-ip", ip);
  const secret = process.env.BACKEND_PROXY_SECRET;
  if (secret) headers.set("x-aeo-proxy-secret", secret);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: "/api/:path*",
};
