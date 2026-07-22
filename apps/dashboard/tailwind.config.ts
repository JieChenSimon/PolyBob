import type { Config } from "tailwindcss";

/**
 * PolyBob design tokens (light theme).
 *
 * Palette restraint: one accent (sky), three semantic tones
 * (emerald=positive, rose=negative, amber=warning/stale) and the warm
 * stone gray ramp for everything else. Components should not introduce
 * colors outside this set.
 */
const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Page canvas: near-white with a warm tint.
        canvas: "#FAFAF8",
        accent: {
          DEFAULT: "#0284c7", // sky-600
          soft: "#f0f9ff", // sky-50
          border: "#bae6fd", // sky-200
          strong: "#0369a1", // sky-700
        },
        positive: {
          DEFAULT: "#059669", // emerald-600
          soft: "#ecfdf5",
          border: "#a7f3d0",
        },
        negative: {
          DEFAULT: "#e11d48", // rose-600
          soft: "#fff1f2",
          border: "#fecdd3",
        },
        warning: {
          DEFAULT: "#d97706", // amber-600
          soft: "#fffbeb",
          border: "#fde68a",
        },
      },
      fontFamily: {
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      maxWidth: {
        shell: "1380px",
      },
    },
  },
  plugins: [],
};
export default config;
