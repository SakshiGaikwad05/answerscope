"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AUTH_CHANGED_EVENT, api, type User } from "@/lib/api";

const navCls = (active: boolean) =>
  `rounded-lg px-3 py-2 ${active ? "bg-slate-100 font-medium text-slate-900" : "text-slate-700 hover:bg-slate-100"}`;

export function AuthNav() {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .me()
        .then((u) => !cancelled && setUser(u))
        .catch(() => !cancelled && setUser(null));
    void load();
    // Login and logout announce themselves so the header updates immediately.
    window.addEventListener(AUTH_CHANGED_EVENT, load);
    return () => {
      cancelled = true;
      window.removeEventListener(AUTH_CHANGED_EVENT, load);
    };
  }, [pathname]);

  async function logout() {
    await api.logout().catch(() => undefined);
    setUser(null);
    window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
    router.push("/login");
  }

  if (user === undefined) return <div className="h-9" aria-hidden="true" />;

  if (user === null) {
    return (
      <div className="flex items-center gap-1 text-sm">
        <Link href="/login" className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100">Log in</Link>
        <Link href="/register" className="rounded-lg bg-accent px-3 py-2 font-medium text-white hover:bg-accent-hover">
          Sign up
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1 text-sm">
      <Link href="/projects" className={navCls(pathname.startsWith("/projects") && pathname !== "/projects/new")}>Projects</Link>
      <Link href="/keys" className={navCls(pathname === "/keys")}>API keys</Link>
      <Link href="/projects/new" className="rounded-lg bg-accent px-3 py-2 font-medium text-white hover:bg-accent-hover">
        New project
      </Link>
      <span className="ml-2 hidden max-w-[12rem] truncate text-slate-500 sm:inline" title={user.email}>{user.email}</span>
      <button onClick={logout} className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100">Log out</button>
    </div>
  );
}
