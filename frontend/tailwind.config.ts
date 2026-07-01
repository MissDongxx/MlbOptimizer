import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
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
