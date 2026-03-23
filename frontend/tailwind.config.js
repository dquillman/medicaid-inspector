/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#f0f4ff',
          100: '#e0eaff',
          500: '#3b6bff',
          600: '#2755e0',
          700: '#1a3db8',
          900: '#0a1a6b',
        },
        risk: {
          low:    '#22c55e',
          medium: '#f59e0b',
          high:   '#ef4444',
        },
      },
    },
  },
  plugins: [],
}
