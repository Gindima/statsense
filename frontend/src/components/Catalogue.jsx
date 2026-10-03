import { useEffect, useState } from "react";

import { getCatalogue } from "../lib/api";
import { nombre } from "../lib/format";

/**
 * Inventaire des données chargées.
 *
 * Ce n'est pas une page annexe : elle rend l'engagement de traçabilité
 * vérifiable. Tout ce que la plateforme exploite y figure, avec sa
 * granularité, sa période et sa provenance — y compris ce qu'elle ne
 * peut pas faire.
 */

const GRANULARITE = {
  national: "National",
  region: "Région",
  departement: "Département",
  commune: "Commune",
  quartier: "Quartier",
};

export default function Catalogue() {
  const [data, setData] = useState(null);
  const [erreur, setErreur] = useState(null);

  useEffect(() => {
    getCatalogue().then(setData).catch((e) => setErreur(e.message));
  }, []);

  if (erreur) return <p className="text-signal text-sm">{erreur}</p>;
  if (!data) {
    return <div className="h-64 bloc animate-pulse" aria-busy="true" />;
  }

  const parSource = data.indicateurs.reduce((acc, i) => {
    (acc[i.source.nom] ||= []).push(i);
    return acc;
  }, {});

  return (
    <div className="space-y-10">
      <div className="flex gap-10 flex-wrap">
        {[
          { v: data.indicateurs.length, l: "indicateurs" },
          { v: data.total_observations, l: "observations" },
          { v: Object.keys(parSource).length, l: "jeux de données" },
          { v: data.zones?.quartier || 0, l: "quartiers" },
        ].map((s) => (
          <div key={s.l}>
            <div className="font-chiffre text-3xl tabulaire">
              {nombre(s.v)}
            </div>
            <div className="text-xs text-sourdine">{s.l}</div>
          </div>
        ))}
      </div>

      {Object.entries(parSource).map(([nomSource, indicateurs]) => (
        <section key={nomSource}>
          <h3 className="font-medium mb-1">{nomSource}</h3>
          {indicateurs[0].source.url && (
            <a
              href={indicateurs[0].source.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-sourdine underline underline-offset-2
                         hover:text-encre"
            >
              {indicateurs[0].source.plateforme}
            </a>
          )}

          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm min-w-[38rem]">
              <thead>
                <tr className="text-left text-sourdine border-b border-filet">
                  <th className="font-medium pb-2">Indicateur</th>
                  <th className="font-medium pb-2">Unité</th>
                  <th className="font-medium pb-2">Niveau le plus fin</th>
                  <th className="font-medium pb-2">Période</th>
                  <th className="font-medium pb-2 text-right">Valeurs</th>
                </tr>
              </thead>
              <tbody>
                {indicateurs.map((i) => (
                  <tr
                    key={i.code}
                    className="border-b border-filet/60 last:border-0"
                  >
                    <td className="py-2">
                      {i.libelle}
                      {i.derive && (
                        <span className="text-xs text-sourdine">
                          {" "}
                          · calculé
                        </span>
                      )}
                    </td>
                    <td className="py-2 text-sourdine">{i.unite}</td>
                    <td className="py-2 text-sourdine">
                      {GRANULARITE[i.granularite_min] || i.granularite_min}
                    </td>
                    <td className="py-2 text-sourdine tabulaire">
                      {i.periodes
                        ? i.periodes.debut === i.periodes.fin
                          ? i.periodes.debut
                          : `${i.periodes.debut}–${i.periodes.fin}`
                        : "—"}
                    </td>
                    <td className="py-2 text-right tabulaire text-sourdine">
                      {i.observations ? nombre(i.observations) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
