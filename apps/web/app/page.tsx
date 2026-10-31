"use client";

import { useEffect, useState } from "react";

import { PlotWorkbench } from "@/components/plot-workbench";
import { StatusPill } from "@/components/status-pill";
import { copy, type Language } from "@/lib/copy";

type Theme = "light" | "dark";

export default function Home() {
  const [language, setLanguage] = useState<Language>("en");
  const [theme, setTheme] = useState<Theme>("light");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const storedLanguage = window.localStorage.getItem("canonguard.language");
    const storedTheme = window.localStorage.getItem("canonguard.theme");
    const nextLanguage: Language = storedLanguage === "zh" ? "zh" : "en";
    const nextTheme: Theme = storedTheme === "dark" ? "dark" : "light";
    setLanguage(nextLanguage);
    setTheme(nextTheme);
    document.documentElement.dataset.theme = nextTheme;
    document.documentElement.lang = nextLanguage === "zh" ? "zh-CN" : "en";
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    window.localStorage.setItem("canonguard.language", language);
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language, ready]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    if (ready) {
      window.localStorage.setItem("canonguard.theme", theme);
    }
  }, [theme, ready]);

  const t = copy[language];

  return (
    <main className="min-h-screen">
      <div className="mx-auto max-w-[1440px] px-5 pb-20 pt-6 sm:px-8 lg:px-12">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border)] pb-5">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="font-display text-2xl font-semibold tracking-tight text-[var(--text)]">
              CanonGuard
            </span>
            <span className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
              {t.brandTagline}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <StatusPill language={language} />
            <div className="flex items-center border border-[var(--border-strong)]">
              {(["light", "dark"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setTheme(value)}
                  className={`px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.14em] transition ${
                    theme === value
                      ? "bg-[var(--text)] text-[var(--accent-contrast)]"
                      : "text-[var(--muted)] hover:text-[var(--text)]"
                  }`}
                >
                  {value}
                </button>
              ))}
            </div>
            <div className="flex items-center border border-[var(--border-strong)]">
              <button
                type="button"
                onClick={() => setLanguage("en")}
                className={`px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.14em] transition ${
                  language === "en"
                    ? "bg-[var(--text)] text-[var(--accent-contrast)]"
                    : "text-[var(--muted)] hover:text-[var(--text)]"
                }`}
              >
                EN
              </button>
              <button
                type="button"
                onClick={() => setLanguage("zh")}
                className={`px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.14em] transition ${
                  language === "zh"
                    ? "bg-[var(--text)] text-[var(--accent-contrast)]"
                    : "text-[var(--muted)] hover:text-[var(--text)]"
                }`}
              >
                中
              </button>
            </div>
          </div>
        </header>

        <section className="py-12 lg:py-16">
          <p className="font-mono text-[12px] uppercase tracking-[0.18em] text-[var(--accent)]">
            {t.heroEyebrow}
          </p>
          <h1 className="mt-5 max-w-4xl font-display text-[3.2rem] font-semibold leading-[0.98] tracking-[-0.035em] text-[var(--text)] sm:text-6xl lg:text-[4.6rem]">
            {t.heroTitle}
          </h1>
        </section>

        {ready ? (
          <PlotWorkbench language={language} />
        ) : (
          <div className="h-72 animate-pulse border border-[var(--border)] bg-[var(--surface)]" />
        )}
      </div>
    </main>
  );
}
