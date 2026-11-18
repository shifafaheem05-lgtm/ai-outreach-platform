/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#f5f3ff',
          100: '#ede9fe',
          200: '#ddd6fe',
          300: '#c4b5fd',
          400: '#a78bfa',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
          800: '#5b21b6',
          900: '#4c1d95',
        },
        ink: {
          800: '#17142b',
          900: '#0f0d1f',
          950: '#0a0816',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,12,40,0.04), 0 4px 16px rgba(16,12,40,0.06)',
      },
    },
  },
  plugins: [],
}
