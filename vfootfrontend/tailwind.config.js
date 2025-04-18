/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
    theme: {
      // ...
      extend: {
        // ...
        colors: {
          'custom-gray': {
            100: '#F9F9F9',
            200: '#E1E1E1',
            400: '#97a2c6',
            DEFAULT: '#7B8294',
            600: '#3a4662',
            700: '#252e44',
            800: '#1f2638',
            900: '#252831',
          },
          'custom-green': {
            300: '#6FFFFD',
            DEFAULT: '#00D4CF',
            500: '#04C3A3',
          },
          'custom-yellow': {
            DEFAULT: '#FFCC00',
          },
          'custom-orange': {
            DEFAULT: '#FF5411',
          },
          'custom-red': {
            DEFAULT: '#FF2C4F',
          },
          'custom-blue': {
            DEFAULT: '#2380FF',
          },
          'team-golden': {
            primary: '#FFBA00',
            secondary: '#FF9000',
          },
          'team-emerald': {
            primary: '#00D3AF',
            secondary: '#00B394',
          },
          'team-crimson': {
            primary: '#FF2B4F',
            secondary: '#C70021',
          },
          'team-blue': {
            primary: '#285BFF',
            secondary: '#0330C1',
          },
          'team-purple': {
            primary: '#9147FF',
            secondary: '#5B26AA',
          },
          'team-green': {
            primary: '#95EC0B',
            secondary: '#67A504',
          },
          'team-aqua': {
            primary: '#00C6FF',
            secondary: '#007EA1',
          },
          'team-silver': {
            primary: '#B0B7C1',
            secondary: '#5F656F',
          },
        }
      },
    },



  plugins: [],
};
