import type { Config } from 'tailwindcss';

// Token names mirror Tokens.dc.html; every colour resolves to a CSS variable from src/styles/tokens.css.
const tokens = [
  'bg', 'surface', 'surface-2', 'surface-3', 'border', 'border-strong', 'text', 'text-2', 'text-3',
  'accent', 'accent-hover', 'accent-soft', 'accent-text', 'on-accent', 'focus',
  'success', 'success-soft', 'warning', 'warning-soft', 'warning-solid', 'danger', 'danger-soft', 'info', 'info-soft',
  'dry', 'dry-soft', 'dry-hatch', 'live', 'live-ink',
  'plat-naukri', 'plat-instahyre', 'plat-indeed', 'plat-linkedin', 'plat-wellfound', 'plat-hirist',
];

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: Object.fromEntries(tokens.map((t) => [t, `var(--${t})`])),
      fontFamily: {
        sans: ['"Geist Sans"', 'Geist', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
        mono: ['"Geist Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['11px', { lineHeight: '16px', letterSpacing: '.06em' }],
        xs: ['12px', '16px'],
        sm: ['13px', '19px'],
        md: ['14px', '20px'],
        lg: ['19px', '24px'],
        xl: ['20px', '26px'],
        '2xl': ['24px', '30px'],
        '3xl': ['28px', '32px'],
      },
      borderRadius: {
        xs: 'var(--radius-xs)', sm: 'var(--radius-sm)', md: 'var(--radius-md)',
        lg: 'var(--radius-lg)', xl: 'var(--radius-xl)',
      },
      boxShadow: { sm: 'var(--shadow-sm)', md: 'var(--shadow-md)', lg: 'var(--shadow-lg)' },
      transitionTimingFunction: { DEFAULT: 'var(--ease)' },
      transitionDuration: { fast: '120ms', DEFAULT: '180ms', slow: '240ms' },
      keyframes: {
        shimmer: { '0%': { backgroundPosition: '200% 0' }, '100%': { backgroundPosition: '-200% 0' } },
        pulse: { '50%': { opacity: '.35' } },
      },
      animation: {
        shimmer: 'shimmer 1.3s linear infinite',
        'live-pulse': 'pulse 1.4s infinite',
      },
    },
  },
  plugins: [],
} satisfies Config;
