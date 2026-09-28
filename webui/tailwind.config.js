import animate from "tailwindcss-animate";
import typography from "@tailwindcss/typography";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    "../nanobot/channels/*/webui/**/*.{ts,tsx}",
    "./node_modules/streamdown/dist/*.js",
  ],
  theme: {
    container: {
      center: true,
      padding: "1rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          '"Helvetica Neue"',
          "Arial",
          '"Noto Sans"',
          '"Noto Sans SC"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          "sans-serif",
          '"Apple Color Emoji"',
          '"Segoe UI Emoji"',
        ],
        mono: [
          '"JetBrains Mono"',
          '"Fira Code"',
          '"Cascadia Code"',
          '"Source Code Pro"',
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        mark: "var(--radius-mark)",
        compact: "var(--radius-compact)",
        control: "var(--radius-control)",
        floating: "var(--radius-floating)",
        panel: "var(--radius-panel)",
        modal: "var(--radius-modal)",
        prominent: "var(--radius-prominent)",
        hero: "var(--radius-hero)",
        // --radius-pill has existed as a CSS variable since the shape scale was
        // written, but it never had a utility, so `rounded-pill` silently did
        // nothing. MD3 pills are the single most-used shape, so wire it up.
        pill: "var(--radius-pill)",
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        tertiary: {
          DEFAULT: "hsl(var(--tertiary))",
          foreground: "hsl(var(--tertiary-foreground))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        sidebar: {
          DEFAULT: "hsl(var(--sidebar))",
          foreground: "hsl(var(--sidebar-foreground))",
          content: "hsl(var(--sidebar-content))",
          "muted-foreground": "hsl(var(--sidebar-muted-foreground))",
          selected: "hsl(var(--sidebar-selected))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
        },
        settings: {
          canvas: "hsl(var(--settings-canvas))",
          surface: "hsl(var(--settings-surface))",
        },
        // The MD3 surface ladder. Nesting under `surface` is what produces
        // `bg-surface-container`, `bg-surface-container-low`, and so on.
        surface: {
          DEFAULT: "hsl(var(--background))",
          "container-lowest": "hsl(var(--surface-container-lowest))",
          "container-low": "hsl(var(--surface-container-low))",
          container: "hsl(var(--surface-container))",
          "container-high": "hsl(var(--surface-container-high))",
          "container-highest": "hsl(var(--surface-container-highest))",
        },
        "on-surface-variant": "hsl(var(--on-surface-variant))",
        outline: {
          DEFAULT: "hsl(var(--outline))",
          variant: "hsl(var(--outline-variant))",
        },
        // NB: `secondary`/`secondary-foreground` already ARE MD3's
        // secondary-container/on-secondary-container pair, and `muted` is
        // surface-variant. Aliases would give one role two names, which is the
        // drift this file exists to prevent, so they are not repeated here.
        "primary-container": "hsl(var(--primary-container))",
        "on-primary-container": "hsl(var(--on-primary-container))",
        "inverse-surface": "hsl(var(--inverse-surface))",
        "inverse-on-surface": "hsl(var(--inverse-on-surface))",
        "inverse-primary": "hsl(var(--inverse-primary))",
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        info: {
          DEFAULT: "hsl(var(--info))",
          foreground: "hsl(var(--info-foreground))",
        },
      },
      // MD3 elevation. Named by level rather than by size so a call site says
      // how far off the page it is, and so the light/dark shadow colour stays
      // inside the token instead of every caller pairing a dark: override.
      boxShadow: {
        "elevation-1": "var(--elevation-1)",
        "elevation-2": "var(--elevation-2)",
        "elevation-3": "var(--elevation-3)",
        "elevation-4": "var(--elevation-4)",
      },
      // MD3 type scale. Sizes are fixed; only the family, weight and colour are
      // free. `label-lg` at 13px is the one step MD3 does not have -- it is
      // kept because the sidebar, list rows and settings labels are built at
      // that density, and rounding 123 call sites up to 14px would reflow
      // truncation points rather than restyle them.
      fontSize: {
        "label-sm": ["0.6875rem", { lineHeight: "1rem" }],
        "label-md": ["0.75rem", { lineHeight: "1rem" }],
        "label-lg": ["0.8125rem", { lineHeight: "1.125rem" }],
        "body-sm": ["0.8125rem", { lineHeight: "1.25rem" }],
        "body-md": ["0.875rem", { lineHeight: "1.25rem" }],
        "body-lg": ["1rem", { lineHeight: "1.5rem" }],
        "title-md": ["1rem", { lineHeight: "1.5rem" }],
        "title-lg": ["1.375rem", { lineHeight: "1.75rem" }],
        "headline-sm": ["1.5rem", { lineHeight: "2rem" }],
        "headline-md": ["1.75rem", { lineHeight: "2.25rem" }],
      },
      // MD3 motion curves. The same three values are exposed as --ease-* CSS
      // variables in globals.css so hand-written CSS and utility classes share
      // one definition instead of each component retyping the bezier.
      transitionTimingFunction: {
        standard: "cubic-bezier(0.2, 0, 0, 1)",
        decelerate: "cubic-bezier(0, 0, 0, 1)",
        accelerate: "cubic-bezier(0.3, 0, 1, 1)",
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
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [animate, typography],
};
