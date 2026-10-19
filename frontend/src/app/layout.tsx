import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import { AuthNav } from "@/components/AuthNav";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AnswerScope — AI answer visibility",
  description: "See how visible your brand is in AI-generated answers, and what to fix.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
          Skip to content
        </a>
        <header className="border-b border-slate-200 bg-white">
          <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6" aria-label="Main">
            <Link href="/" className="flex items-center gap-2 font-semibold text-slate-900">
              <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm text-white">A</span>
              AnswerScope
            </Link>
            <Suspense fallback={<div className="h-9" aria-hidden="true" />}>
              <AuthNav />
            </Suspense>
          </nav>
        </header>
        <main id="main" className="flex-1">{children}</main>
        <footer className="border-t border-slate-200 bg-white py-6 text-center text-xs text-slate-500">
          AI provider answers come from APIs and can differ from consumer apps. No change guarantees AI citations or rankings.
        </footer>
      </body>
    </html>
  );
}
