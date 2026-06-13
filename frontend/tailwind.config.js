/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        // Space Grotesk = the human voice (labels, prose). IBM Plex Mono = the
        // machine voice (every number, NPI, score, $, timestamp). Never cross.
        display: ['Space Grotesk', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        // demoted: informational / non-threat tags ONLY
        brand: {
          50:  '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        },

        // NOCTURNE elevation ramp — proximity to the lamp
        void:  '#030712',
        abyss: '#060b14',
        surface: { 0: '#0A0F18', 1: '#0E141F', 2: '#141C2A' },
        hairline: { DEFAULT: '#1C2636', hot: '#2A3850' },

        // THE single accent — Filament (cold amber, the desk lamp)
        filament: { core: '#E8B45A', dim: '#9A7B3E' },

        // threat ramp — 5 discrete stops (continuous lerp lives in lib/threat.ts)
        threat: {
          clear:    '#3FBF8F', // 0–20
          low:      '#7FB04A', // 20–40
          medium:   '#E0A53A', // 40–60
          high:     '#E2603A', // 60–80
          critical: '#D7263D', // 80–100
        },

        // text tiers (AA-verified on surface-1 #0E141F)
        ink: {
          primary:   '#EAF0F8', // 15.8:1  headings, key numbers
          secondary: '#AEBACA', //  8.9:1  body, labels
          tertiary:  '#7A879B', //  4.8:1  captions, metadata — AA floor for data
          ghost:     '#4A576B', //  2.9:1  DECORATIVE ONLY — never data/SR-read
        },

        // legacy — keep for back-compat with existing .badge-* + @media print
        risk: {
          low:    '#22c55e',
          medium: '#f59e0b',
          high:   '#ef4444',
        },
      },
      boxShadow: {
        'glow-filament': '0 0 18px 2px rgba(232,180,90,0.14), 0 0 4px 1px rgba(232,180,90,0.10)',
        'glow-critical': '0 0 22px 3px rgba(215,38,61,0.22)',
      },
    },
  },
  plugins: [],
}
