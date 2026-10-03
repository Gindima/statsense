import { useState } from "react";

/**
 * Le plan de requête, affiché entre la question et le résultat.
 *
 * C'est la pièce maîtresse de l'interface. Elle rend visible la
 * séparation qui fonde le projet : le modèle a traduit la question en
 * cet objet, et rien d'autre. Le calcul qui suit n'en dépend plus.
 *
 * Replié, il tient en une ligne lisible par tous ; déplié, il montre le
 * JSON exact — ce qu'un évaluateur voudra vérifier.
 */

const LIBELLES = {
  valeur_simple: "valeur",
  classement: "classement",
  evolution: "évolution",
  geographique: "carte",
};

const NIVEAUX = {
  national: "national",
  region: "par région",
  departement: "par département",
  commune: "par commune",
  quartier: "par quartier",
};

export default function PlanRequete({ plan, meta }) {
  const [ouvert, setOuvert] = useState(false);
  if (!plan) return null;

  const origine = meta?.origine;
  const depuisCache = meta?.cache;

  const resume = [
    LIBELLES[plan.methode] || plan.methode,
    plan.indicateur,
    plan.niveau && NIVEAUX[plan.niveau],
    plan.zones?.length ? plan.zones.join(", ") : null,
    plan.top_n ? `${plan.top_n} premiers` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="border-l-2 border-echelle-3 bg-echelle-1/40 pl-4 py-3">
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="text-sourdine text-sm shrink-0">
          Traduit en requête
        </span>
        <code className="font-code text-sm text-echelle-5 break-words">
          {resume}
        </code>
      </div>

      <div className="mt-2 flex items-center gap-4 flex-wrap text-xs text-sourdine">
        <button
          type="button"
          onClick={() => setOuvert(!ouvert)}
          className="underline underline-offset-2 hover:text-encre"
          aria-expanded={ouvert}
        >
          {ouvert ? "Masquer le détail" : "Voir le plan complet"}
        </button>

        {origine === "repli" && (
          <span className="text-signal">
            Modèle indisponible — plan reconstruit par mots-clés
          </span>
        )}
        {depuisCache && <span>Réponse déjà calculée</span>}
        {meta?.latence_s > 0 && <span>{meta.latence_s}s d'analyse</span>}
      </div>

      {ouvert && (
        <pre className="mt-3 font-code text-xs leading-relaxed text-encre bg-carte border border-filet rounded p-3 overflow-x-auto">
          {JSON.stringify(plan, null, 2)}
        </pre>
      )}
    </div>
  );
}
