"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { Button, Card } from "@/components/ui";
import { AUTH_CHANGED_EVENT, api } from "@/lib/api";

const noopSubscribe = () => () => {};

/** Only allow redirects to paths on this site, never to another origin. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/projects";
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const search = useSearchParams();
  const interactive = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isLogin = mode === "login";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await (isLogin ? api.login(email, password) : api.register(email, password));
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
      router.push(safeNext(search.get("next")));
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-md px-4 py-12 sm:px-6">
      <h1 className="text-2xl font-semibold text-slate-900">{isLogin ? "Log in" : "Create your account"}</h1>
      <p className="mt-1 text-sm text-slate-500">
        {isLogin ? "Welcome back." : "Your projects and results are private to your account."}
      </p>
      <Card className="mt-6">
        <form onSubmit={onSubmit} method="post" className="space-y-4" noValidate>
          <div>
            <label htmlFor="email" className="text-sm font-medium text-slate-800">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              disabled={!interactive}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="password" className="text-sm font-medium text-slate-800">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              required
              disabled={!interactive}
              minLength={isLogin ? undefined : 8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              aria-describedby={isLogin ? undefined : "password-help"}
            />
            {!isLogin && <p id="password-help" className="mt-1 text-xs text-slate-500">At least 8 characters.</p>}
          </div>
          {error && <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
          <Button type="submit" className="w-full" loading={submitting} disabled={!interactive}>
            {!interactive ? "Loading…" : isLogin ? "Log in" : "Create account"}
          </Button>
        </form>
      </Card>
      <p className="mt-4 text-center text-sm text-slate-600">
        {isLogin ? (
          <>No account? <Link href={`/register${search.get("next") ? `?next=${encodeURIComponent(search.get("next")!)}` : ""}`} className="font-medium text-indigo-700 hover:underline">Sign up</Link></>
        ) : (
          <>Already have an account? <Link href="/login" className="font-medium text-indigo-700 hover:underline">Log in</Link></>
        )}
      </p>
    </div>
  );
}
