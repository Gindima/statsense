/**
 * Provenance des chiffres.
 *
 * Affichée sous chaque résultat sans exception : c'est l'engagement de
 * traçabilité, et il ne souffre pas d'être optionnel.
 */
export default function Sources({ sources }) {
  if (!sources?.length) return null;

  return (
    <div className="border-t border-filet pt-3 mt-5 text-xs text-sourdine space-y-1">
      {sources.map((s, i) => (
        <div key={i}>
          <span>Source : </span>
          {s.url ? (
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2 hover:text-encre"
            >
              {s.nom}
            </a>
          ) : (
            <span>{s.nom}</span>
          )}
          {s.date_extraction && (
            <span> · extraction du {s.date_extraction}</span>
          )}
        </div>
      ))}
    </div>
  );
}
