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
// Runs synchronously before React hydrates so the FIRST paint already has
// the correct theme — no white flash for users who picked light mode.
// Reads localStorage("uteki-theme"); only sets data-theme="light" when
// explicit (so dark remains the default for first-time visitors).
const themeBootstrap = `
try {
  var t = localStorage.getItem('uteki-theme');
  if (t === 'light') document.documentElement.setAttribute('data-theme', 'light');
} catch (e) {}
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="zh-CN"
      suppressHydrationWarning
      className={`${fraunces.variable} ${newsreader.variable} ${mono.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body className="font-body">{children}</body>
    </html>
  );
}
