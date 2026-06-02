/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
        // ── Console design tokens (additive; from jarvis_frontend) ──
        "bg-void": "#0a0e17",
        "bg-floor": {
          DEFAULT: "#111827",
          living: "#0f172a",
          office: "#111827",
          control: "#0a0e17",
        },
        "bg-panel": "#111827ee",
        "bg-panel-hover": "#1e293bee",
        "bg-input": "#0f172a",
        "wall-outer": "#F0F0F0",
        "wall-inner": "#E0E0E0",
        "cyan-primary": "#22d3ee",
        "amber-warm": "#fbbf24",
        "white-light": "#f8fafc",
        "slate-dark": "#1e293b",
        "text-primary": "#f8fafc",
        "text-secondary": "#94a3b8",
        "text-disabled": "#475569",
        success: "#4ade80",
        warning: "#fbbf24",
        error: "#ef4444",
        info: "#22d3ee",
      },
      fontFamily: {
        clash: ['"Clash Display"', 'system-ui', 'sans-serif'],
        inter: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      borderRadius: {
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xs: "calc(var(--radius) - 6px)",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        "cyan-glow": "0 0 20px rgba(34, 211, 238, 0.4)",
        "cyan-glow-lg": "0 8px 32px rgba(34, 211, 238, 0.08)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "caret-blink": {
          "0%,70%,100%": { opacity: "1" },
          "20%,50%": { opacity: "0" },
        },
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-6px)" },
        },
        "glow-pulse": {
          "0%, 100%": { boxShadow: "0 0 20px rgba(34, 211, 238, 0.15)" },
          "50%": { boxShadow: "0 0 30px rgba(34, 211, 238, 0.3)" },
        },
        "ring-pulse": {
          "0%": { transform: "scale(1)", opacity: "0.6" },
          "100%": { transform: "scale(1.8)", opacity: "0" },
        },
        "skeleton-shimmer": {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "cyan-flash": {
          "0%": { backgroundColor: "rgba(34, 211, 238, 0.3)" },
          "100%": { backgroundColor: "transparent" },
        },
        "slide-in-right": {
          from: { transform: "translateX(100%)", opacity: "0" },
          to: { transform: "translateX(0)", opacity: "1" },
        },
        "fade-in-up": {
          from: { transform: "translateY(8px)", opacity: "0" },
          to: { transform: "translateY(0)", opacity: "1" },
        },
        "data-flow": {
          "0%": { strokeDashoffset: "100" },
          "100%": { strokeDashoffset: "0" },
        },
        "particle-drift": {
          "0%": { transform: "translate(0, 0)" },
          "25%": { transform: "translate(var(--drift-x, 50px), calc(var(--drift-y, 30px) * -0.3))" },
          "50%": { transform: "translate(calc(var(--drift-x, 50px) * 0.5), calc(var(--drift-y, 30px) * 0.4))" },
          "75%": { transform: "translate(calc(var(--drift-x, 50px) * -0.3), var(--drift-y, 30px))" },
          "100%": { transform: "translate(0, 0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "caret-blink": "caret-blink 1.25s ease-out infinite",
        "pulse-dot": "pulse-dot 2s ease-in-out infinite",
        float: "float 3s ease-in-out infinite",
        "glow-pulse": "glow-pulse 2s ease-in-out infinite",
        "ring-pulse": "ring-pulse 1.5s ease-out infinite",
        skeleton: "skeleton-shimmer 1.5s ease-in-out infinite",
        "cyan-flash": "cyan-flash 0.6s ease-out",
        "slide-in-right": "slide-in-right 0.3s ease-out forwards",
        "fade-in-up": "fade-in-up 0.3s ease-out forwards",
        "particle-drift": "particle-drift var(--drift-duration, 30s) ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
