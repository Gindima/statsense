/**
 * Refus méthodologique.
 *
 * Le système ne répond pas toujours, et c'est délibéré : plutôt que de
 * diviser un agrégat national par quatorze ou d'inventer un indicateur
 * absent du catalogue, il dit ce qui manque et propose une piste.
 *
 * Traité visuellement comme une réponse à part entière, pas comme une
 * erreur : rien ici n'a échoué.
 */

const MOTIFS = {
  granularite_indisponible: "Donnée non publiée à ce niveau",
  periode_non_couverte: "Période hors couverture",
  indicateur_absent: "Indicateur absent du catalogue",
  dimension_invalide: "Ventilation indisponible",
  donnee_absente: "Aucune donnée pour cette combinaison",
  serie_trop_courte: "Série trop courte",
  aucun_candidat: "Aucun indicateur correspondant",
  non_agregeable: "Agrégation impossible",
  zone_inconnue: "Lieu non reconnu",
  zone_ambigue: "Plusieurs lieux portent ce nom",
  age_non_traite: "Groupe d'âge non traité",
  analyse_non_traitee: "Analyse non proposée",

};

export default function Refus({ reponse, onSuggestion }) {
  const { message, motif, alternatives } = reponse;

  return (
    <section className="bloc border-signal/30 bg-signalclair p-6 sm:p-7">
      <div className="text-xs text-signal mb-2">
        {MOTIFS[motif] || "Demande non traitable"}
      </div>

      <p className="max-w-lecture leading-relaxed">{message}</p>

      {alternatives?.length > 0 && (
        <div className="mt-5">
          <div className="text-sm text-sourdine mb-2">
            Ce qui est disponible
          </div>
          <div className="flex flex-wrap gap-2">
            {alternatives.map((a, i) => (
              <button
                key={i}
                type="button"
                onClick={() => onSuggestion?.(a)}
                className="text-sm bg-carte border border-filet rounded px-3 py-1.5
                           hover:border-echelle-3 transition-colors text-left"
              >
                {a}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
