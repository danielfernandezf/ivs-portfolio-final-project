/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bloomberg: {
          bg: '#0a0a0a',
          panel: '#111111',
          border: '#1e1e1e',
          amber: '#f5a623',
          'amber-dim': '#8b5e13',
          electric: '#00aaff',
          'electric-dim': '#005580',
          green: '#00cc44',
          red: '#ff3333',
          'text-primary': '#e8e8e8',
          'text-secondary': '#888888',
          'text-muted': '#444444',
        },
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', '"Fira Code"', '"Courier New"', 'monospace'],
        sans: ['"Inter"', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': '0.65rem',
        xs: '0.75rem',
      },
    },
  },
  plugins: [],
}
