import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

const config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./pages/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  darkMode: ["class"],
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        background: "#050606",
        foreground: "#f4f4f1",
        card: "#0d0f0f",
        border: "#272727",
        muted: "#1f2222",
        "muted-foreground": "#9f9f9a",
        secondary: "#202323",
        "secondary-foreground": "#f4f4f1",
      },
      borderRadius: {
        lg: "8px",
        md: "6px",
        sm: "4px",
      },
    },
  },
  plugins: [tailwindcssAnimate],
} satisfies Config;

export default config;
