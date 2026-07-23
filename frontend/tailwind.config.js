/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
          50: 'hsl(var(--primary) / 0.08)',
          100: 'hsl(var(--primary) / 0.15)',
          200: 'hsl(var(--primary) / 0.25)',
          300: 'hsl(var(--primary) / 0.40)',
          400: 'hsl(var(--primary) / 0.60)',
          500: 'hsl(var(--primary) / 0.80)',
          600: 'hsl(var(--primary))',
          700: 'hsl(var(--primary) / 0.85)',
          800: 'hsl(var(--primary) / 0.70)',
          900: 'hsl(var(--primary) / 0.55)',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
        // Memory 域三档圆角原子:sm=控件/chip, md=列表项/分段控件, lg=页面级卡片
        'mem-sm': '6px',
        'mem-md': '10px',
        'mem-lg': '16px',
      },
      opacity: {
        92: '0.92',
      },
    },
  },
  plugins: [],
}
