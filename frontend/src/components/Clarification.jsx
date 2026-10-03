/**
 * Demande de précision.
 *
 * Quand le modèle n'est pas sûr, il le dit plutôt que de deviner. Les
 * indicateurs candidats sont proposés tels que la recherche les a
 * classés : l'utilisateur tranche.
 */
export default function Clarification({ reponse, onChoix }) {
  const { message, suggestions } = reponse;

  return (
    <section className="bloc p-6 sm:p-7">
      <p className="max-w-lecture leading-relaxed">{message}</p>

      {suggestions?.length > 0 && (
        <div className="mt-5">
          <div className="text-sm text-sourdine mb-2">
            Vouliez-vous dire
          </div>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s.code}
                type="button"
                onClick={() => onChoix?.(s.libelle)}
                className="text-sm border border-filet rounded px-3 py-1.5
                           hover:border-echelle-3 hover:bg-echelle-1/50
                           transition-colors"
              >
                {s.libelle}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
