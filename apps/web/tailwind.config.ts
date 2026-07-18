import type { Config } from "tailwindcss";

/**
 * Design tokens from docs/04-UI-DESIGN.md §5.
 * Light-mode values are the source of truth for the exported screens.
 * Dark-mode values are wired as CSS variables (see styles/index.css) so the
 * palette can be flipped later without touching component code.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "var(--color-background)",
        surface: "var(--color-surface)",
        "surface-subtle": "var(--color-surface-subtle)",
        "text-primary": "var(--color-text-primary)",
        "text-secondary": "var(--color-text-secondary)",
        border: "var(--color-border)",
        primary: "var(--color-primary)",
        "primary-hover": "var(--color-primary-hover)",
        info: "var(--color-info)",
        warning: "var(--color-warning)",
        danger: "var(--color-danger)",
        success: "var(--color-success)",
        twist: "var(--color-twist)",
        highlight: "var(--color-highlight)",
      },
      fontFamily: {
        ui: ["Inter", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "sans-serif"],
        serif: ["Noto Serif SC", "Source Han Serif SC", "Songti SC", "serif"],
      },
      fontSize: {
        // role -> [size, lineHeight] from §5.2
        "page-title": ["24px", { lineHeight: "32px", fontWeight: "650" }],
        "panel-title": ["16px", { lineHeight: "24px", fontWeight: "600" }],
        "body-edit": ["18px", { lineHeight: "32px" }],
        ui: ["14px", { lineHeight: "22px" }],
        label: ["13px", { lineHeight: "20px", fontWeight: "500" }],
        assist: ["12px", { lineHeight: "18px" }],
      },
      borderRadius: {
        control: "6px",
        card: "8px",
      },
      spacing: {
        sidebar: "264px",
        panel: "360px",
        prose: "760px",
        topbar: "52px",
      },
      transitionDuration: {
        panel: "200ms",
      },
    },
  },
  plugins: [],
};

export default config;
