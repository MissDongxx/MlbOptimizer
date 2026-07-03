import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        card: "var(--card)",
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        muted: "var(--muted)",
        "muted-foreground": "var(--muted-foreground)",
        primary: "var(--primary)",
        "primary-foreground": "var(--primary-foreground)",
        "accent-foreground": "var(--accent-foreground)",
        ring: "var(--ring)",
        success: "var(--success)",
        warning: "var(--warning)",
        danger: "var(--danger)",
        ink: "#111827",
        field: "#f7f8fb",
        line: "#d8dee9",
        accent: "#0f766e",
        gold: "#b7791f",
      },
      boxShadow: {
        panel: "0 12px 34px rgba(17, 24, 39, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
