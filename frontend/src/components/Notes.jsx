/**
 * Avertissements méthodologiques.
 *
 * Produits par le moteur, jamais par le modèle : ils sont donc toujours
 * exacts. C'est là que le système signale le glissement annuel sur une
 * série saisonnière, un indicateur non agrégeable ou des zones sans
 * donnée — ce qui distingue une plateforme statistique d'un tableur
 * branché sur un assistant.
 */
export default function Notes({ notes }) {
  if (!notes?.length) return null;

  return (
    <ul className="space-y-1.5">
      {notes.map((n, i) => (
        <li
          key={i}
          className="text-sm text-sourdine leading-relaxed pl-4 relative"
        >
          <span
            className="absolute left-0 top-[0.6em] w-2 h-px bg-sourdine"
            aria-hidden="true"
          />
          {n}
        </li>
      ))}
    </ul>
  );
}
