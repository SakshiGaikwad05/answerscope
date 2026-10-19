"use client";

import Link from "next/link";
import type { ReactNode } from "react";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Card({ children, className, title, description, actions }: {
  children: ReactNode;
  className?: string;
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  loading?: boolean;
};

const BUTTON_VARIANTS = {
  primary: "bg-accent text-white hover:bg-accent-hover disabled:bg-indigo-300",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
  danger: "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50",
};

export function Button({ variant = "primary", loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed",
        BUTTON_VARIANTS[variant],
        className,
      )}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function ButtonLink({ href, children, variant = "primary", className }: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary";
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
        BUTTON_VARIANTS[variant],
        className,
      )}
    >
      {children}
    </Link>
  );
}

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg className={cx("animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 py-10 text-sm text-slate-500 justify-center">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
      <p className="font-medium">Something went wrong</p>
      <p className="mt-1">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-3 font-medium underline underline-offset-2">
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <p className="font-medium text-slate-900">{title}</p>
      {description && <div className="mx-auto mt-1 max-w-md text-sm text-slate-500">{description}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

const BADGE_TONES = {
  neutral: "bg-slate-100 text-slate-700",
  accent: "bg-accent-soft text-indigo-700",
  good: "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200",
  warning: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
  bad: "bg-rose-50 text-rose-800 ring-1 ring-rose-200",
};

export function Badge({ tone = "neutral", children, className }: {
  tone?: keyof typeof BADGE_TONES;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", BADGE_TONES[tone], className)}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === "completed" ? "good" : status === "failed" ? "bad" : status === "running" ? "accent" : "neutral";
  const icon = status === "completed" ? "✓" : status === "failed" ? "✕" : "…";
  return (
    <Badge tone={tone}>
      <span aria-hidden="true">{icon}</span>
      {status}
    </Badge>
  );
}

export function PriorityBadge({ priority }: { priority: "high" | "medium" | "low" }) {
  const tone = priority === "high" ? "bad" : priority === "medium" ? "warning" : "neutral";
  return <Badge tone={tone}>{priority} priority</Badge>;
}

export function StatTile({ label, value, sub, definition }: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  definition: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-medium text-slate-600">{label}</p>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>
      {sub && <p className="mt-1 text-sm text-slate-500">{sub}</p>}
      <p className="mt-3 border-t border-slate-100 pt-2 text-xs leading-relaxed text-slate-500">{definition}</p>
    </div>
  );
}

/** Horizontal bar for a 0-100 value. Text sits beside the bar, never on the color. */
export function Meter({ value, label, emphasize }: { value: number | null; label: string; emphasize?: boolean }) {
  const v = value ?? 0;
  return (
    <div className="flex items-center gap-3" title={`${label}: ${value === null ? "no data" : `${value}%`}`}>
      <div
        className="h-2.5 flex-1 rounded-full bg-slate-100"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value ?? undefined}
      >
        <div
          className={cx("h-2.5 rounded-full", emphasize ? "bg-series-1" : "bg-slate-400")}
          style={{ width: `${Math.max(v, v > 0 ? 2 : 0)}%` }}
        />
      </div>
      <span className="w-12 text-right text-sm tabular-nums text-slate-700">{value === null ? "—" : `${value}%`}</span>
    </div>
  );
}
