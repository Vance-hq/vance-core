import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["'JetBrains Mono'", "'Fira Code'", "'SF Mono'", "Consolas", "monospace"],
      },
      colors: {
        surface: {
          0: "#0a0a0a",
          1: "#111111",
          2: "#191919",
          3: "#222222",
          4: "#2a2a2a",
        },
      },
    },
  },
  plugins: [],
};

export default config;
