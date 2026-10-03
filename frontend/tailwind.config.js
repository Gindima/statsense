/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // La palette descend de l'échelle choroplèthe : le produit
        // culmine sur une carte, et l'écran entier partage sa gamme.
        encre: "#13261F",
        papier: "#F3F4F1",
        carte: "#FFFFFF",
        filet: "#D8DDD7",
        sourdine: "#5D6E64",
        echelle: {
          1: "#E8F0EA",
          2: "#A7CEB8",
          3: "#5DA281",
          4: "#2C7253",
          5: "#12462E",
        },
        // Réservé aux refus et avertissements méthodologiques.
        // Jamais décoratif.
        signal: "#A24E1C",
        signalclair: "#FBF0E7",
      },
      fontFamily: {
        chiffre: ["'Source Serif 4'", "Georgia", "serif"],
        texte: ["'Inter Tight'", "system-ui", "sans-serif"],
        code: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      fontSize: {
        kpi: ["4rem", { lineHeight: "1", letterSpacing: "-0.025em" }],
      },
      maxWidth: { lecture: "68ch" },
    },
  },
  plugins: [],
};
