import type { Metadata } from "next";
import { Fraunces, Newsreader, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  axes: ["opsz", "SOFT", "WONK"],
});

const newsreader = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "uteki — investment research agent",
  description: "Watchlist-driven, schedule-fired, harness-orchestrated investment research.",
};

/**
 * Root layout — just html/body + fonts. The actual chrome (sidebar) lives
 * in ``app/(app)/layout.tsx``; auth pages mount under ``app/(auth)/layout.tsx``
 * with no chrome.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className={`${fraunces.variable} ${newsreader.variable} ${mono.variable}`}>
      <body className="font-body">{children}</body>
    </html>
  );
}
