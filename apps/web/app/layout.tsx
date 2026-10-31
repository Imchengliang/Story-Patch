import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "CanonGuard · Stuck Point Resolver",
  description:
    "Retrieve structurally suitable precedents, map character functions, and get next-step suggestions with verifiable sources.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
