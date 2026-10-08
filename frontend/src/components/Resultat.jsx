import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { compact, nombre, periode, unite as fmtUnite } from "../lib/format";
import Carte from "./Carte";
import Notes from "./Notes";
import Sources from "./Sources";

/**
 * Rendu d'un résultat.
 *
 * Les quatre méthodes du moteur retournent la même structure ; seul
 * `chart_hint` décide de l'affichage. Ajouter une méthode plus tard ne
 * demande qu'une branche de plus ici.
 */

const AXE = { fontSize: 12, fill: "#5D6E64" };

function Infobulle({ active, payload, label, unite }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bloc px-3 py-2 text-sm shadow-sm">
      <div className="text-sourdine text-xs">{label}</div>
      <div className="tabulaire font-medium">
        {nombre(payload[0].value, unite)}
        {fmtUnite(unite)}
      </div>
    </div>
  );
}

function Kpi({ ligne, unite, meta }) {
  return (
    <div>
      <div className="font-chiffre text-kpi tabulaire">
        {nombre(ligne.valeur, unite)}
        <span className="text-3xl text-sourdine">{fmtUnite(unite)}</span>
      </div>
      <div className="mt-1 text-sourdine">
        {[meta?.indicateur, ligne.zone, periode(ligne.periode)]
          .filter(Boolean)
          .join(" · ")}
      </div>
    </div>
  );
}

function Barres({ lignes, unite }) {
  const data = lignes.map((l) => ({
    nom: l.zone,
    valeur: Number(l.valeur),
  }));
  const hauteur = Math.max(220, data.length * 34);

  return (
    <ResponsiveContainer width="100%" height={hauteur}>
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 28 }}>
        <CartesianGrid horizontal={false} stroke="#E4E8E3" />
        <XAxis
          type="number"
          tick={AXE}
          tickFormatter={compact}
          domain={[0, "dataMax"]}
        />
        <YAxis
          type="category"
          dataKey="nom"
          tick={AXE}
          width={128}
          interval={0}
        />
        <Tooltip
          content={<Infobulle unite={unite} />}
          cursor={{ fill: "#E8F0EA" }}
        />
        <Bar dataKey="valeur" fill="#2C7253" radius={[0, 3, 3, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function Courbe({ lignes, unite }) {
  const data = lignes.map((l) => ({
    nom: periode(l.periode),
    valeur: Number(l.valeur),
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
        <CartesianGrid vertical={false} stroke="#E4E8E3" />
        <XAxis dataKey="nom" tick={AXE} minTickGap={24} />
        <YAxis tick={AXE} tickFormatter={compact} width={56} />
        <Tooltip content={<Infobulle unite={unite} />} />
        <Line
          type="monotone"
          dataKey="valeur"
          stroke="#2C7253"
          strokeWidth={2}
          dot={{ r: 2.5, fill: "#2C7253" }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}


function Variation({ meta }) {
  if (!meta) return null;
  const signe = (v) => (Number(v) > 0 ? "+" : "");
  const entre =
    meta.debut && meta.fin
      ? `entre ${periode(meta.debut)} et ${periode(meta.fin)}`
      : "sur la période";

  const chiffres = [];
  if (meta.est_taux) {
    if (meta.variation_absolue != null)
      chiffres.push({
        etiquette: `Écart ${entre}`,
        valeur: `${signe(meta.variation_absolue)}${nombre(meta.variation_absolue, "%")} points`,
      });
  } else {
    if (meta.variation_pct != null)
      chiffres.push({
        etiquette: `Variation ${entre}`,
        valeur: `${signe(meta.variation_pct)}${nombre(meta.variation_pct, "%")} %`,
      });
    if (meta.tcam_pct != null)
      chiffres.push({
        etiquette: "Croissance annuelle moyenne",
        valeur: `${signe(meta.tcam_pct)}${nombre(meta.tcam_pct, "%")} %`,
      });
  }
  if (meta.glissement_pct != null)
    chiffres.push({
      etiquette: "Glissement annuel (T comparé à T-4)",
      valeur: `${signe(meta.glissement_pct)}${nombre(meta.glissement_pct, "%")} %`,
    });

  if (!chiffres.length) return null;
  return (
    <div className="flex gap-10 flex-wrap mb-5">
      {chiffres.map((c) => (
        <div key={c.etiquette}>
          <div className="font-chiffre text-3xl tabulaire">{c.valeur}</div>
          <div className="text-xs text-sourdine mt-0.5">{c.etiquette}</div>
        </div>
      ))}
    </div>
  );
}

function Tableau({ lignes, unite }) {
  const colonneTemps = "periode" in (lignes[0] || {});
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-sourdine border-b border-filet">
          <th className="font-medium pb-2">
            {colonneTemps ? "Période" : "Zone"}
          </th>
          <th className="font-medium pb-2 text-right">
            Valeur{unite && ` (${unite})`}
          </th>
        </tr>
      </thead>
      <tbody>
        {lignes.map((l, i) => (
          <tr key={i} className="border-b border-filet/60 last:border-0">
            <td className="py-1.5">
              {colonneTemps ? periode(l.periode) : l.zone}
            </td>
            <td className="py-1.5 text-right tabulaire">
              {nombre(l.valeur, unite)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Resultat({ resultat, texte }) {
  const { lignes, unite, chart_hint, notes, sources, meta } = resultat;
  if (!lignes?.length) return null;

  // Le texte reprend déjà les avertissements méthodologiques : on
  // n'affiche en note que ce qu'il n'a pas repris, pour ne pas lire
  // deux fois la même phrase.
  const restantes = (notes || []).filter(
    (n) => !texte?.includes(n.slice(0, 40)),
  );

  return (
    <section className="bloc p-6 sm:p-7">
      {chart_hint === "kpi" && (
        <Kpi ligne={lignes[0]} unite={unite} meta={meta} />
      )}

      {chart_hint === "line" && (
        <>
          <Variation meta={meta} unite={unite} />
          <Courbe lignes={lignes} unite={unite} />
        </>
      )}

      {chart_hint === "bar" && <Barres lignes={lignes} unite={unite} />}

      {chart_hint === "choropleth" && (
        <Carte lignes={lignes} unite={unite} meta={meta} />
      )}

      {texte && (
        <p className="mt-6 max-w-lecture leading-relaxed">{texte}</p>
      )}

      {restantes.length > 0 && (
        <div className="mt-4">
          <Notes notes={restantes} />
        </div>
      )}

      {lignes.length > 1 && (
        <details className="mt-5 group">
          <summary className="text-sm text-sourdine cursor-pointer underline underline-offset-2 hover:text-encre marker:content-['']">
            Voir les {lignes.length} valeurs
          </summary>
          <div className="mt-3">
            <Tableau lignes={lignes} unite={unite} />
          </div>
        </details>
      )}

      <Sources sources={sources} />
    </section>
  );
}
