import { useEffect, useRef, useState } from "react";

/**
 * Champ de question.
 *
 * Une seule zone de saisie, mise au premier plan : c'est la promesse du
 * produit. Entrée envoie, Maj+Entrée passe à la ligne.
 */
export default function Question({ onEnvoyer, occupe, valeur, onChange }) {
  const [focus, setFocus] = useState(false);
  const champ = useRef(null);

  useEffect(() => {
    champ.current?.focus();
  }, []);

  const envoyer = () => {
    const q = valeur.trim();
    if (q.length >= 3 && !occupe) onEnvoyer(q);
  };

  return (
    <div
      className={`bloc transition-colors ${
        focus ? "border-echelle-3" : ""
      }`}
    >
      <label htmlFor="question" className="sr-only">
        Votre question sur les statistiques du Sénégal
      </label>
      <textarea
        id="question"
        ref={champ}
        rows={2}
        value={valeur}
        disabled={occupe}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            envoyer();
          }
        }}
        placeholder="Quelles sont les cinq régions les plus peuplées ?"
        className="w-full resize-none bg-transparent px-5 pt-4 pb-2
                   text-lg leading-snug placeholder:text-sourdine/60
                   focus:outline-none disabled:opacity-60"
      />

      <div className="flex items-center justify-between px-5 pb-3">
        <span className="text-xs text-sourdine">
          {occupe ? "Analyse en cours…" : "Entrée pour envoyer"}
        </span>
        <button
          type="button"
          onClick={envoyer}
          disabled={occupe || valeur.trim().length < 3}
          className="text-sm bg-echelle-4 text-papier rounded px-4 py-1.5
                     hover:bg-echelle-5 disabled:opacity-40
                     disabled:cursor-not-allowed transition-colors"
        >
          Interroger
        </button>
      </div>
    </div>
  );
}
