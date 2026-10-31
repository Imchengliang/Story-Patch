/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0b0c0e",
          900: "#111214",
          800: "#17181b",
          700: "#1f2024",
        },
        paper: {
          50: "#f2e9da",
          100: "#e9dfcf",
          200: "#d9cbb6",
          300: "#c8b79e",
          900: "#211b15",
        },
        flare: {
          500: "#e2542e",
          600: "#cf4523",
        },
        fog: "#8a8d92",
      },
      fontFamily: {
        display: [
          '"Fraunces"',
          '"Iowan Old Style"',
          '"Palatino Linotype"',
          '"Songti SC"',
          "serif",
        ],
        sans: [
          '"DM Sans"',
          '"SF Pro Text"',
          "system-ui",
          '"PingFang SC"',
          "sans-serif",
        ],
        mono: ['"IBM Plex Mono"', '"SF Mono"', "Menlo", "monospace"],
      },
      boxShadow: {
        paper:
          "0 1px 0 rgba(255,255,255,0.7) inset, 0 40px 80px -50px rgba(0,0,0,0.95)",
      },
    },
  },
  plugins: [],
};
