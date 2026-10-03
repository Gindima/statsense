import { geoMercator, geoPath } from "d3-geo";
import { useEffect, useMemo, useRef, useState } from "react";

import { getGeo } from "../lib/api";
import { nombre, unite as fmtUnite } from "../lib/format";

/**
 * Carte choroplèthe des régions.
 *
 * Le GeoJSON est servi tel quel par l'API et jamais stocké en base : les
 * valeurs y sont jointes ici, dans le navigateur, par le code de région.
 * Une région sans donnée reste visiblement vide plutôt que d'être
 * masquée — l'absence est une information.
 *
 * Deux relevés au survol, et non un :
 *
 *   - l'infobulle suit le pointeur, pour lire une valeur sans quitter la
 *     région des yeux ;
 *   - la ligne sous la légende reste affichée, porte `aria-live` et sert
 *     aux lecteurs d'écran comme à la navigation au clavier.
 *
 * L'infobulle est donc décorative — `aria-hidden` — et ne remplace rien.
 * Chaque région est atteignable par tabulation : l'infobulle se place
 * alors au centroïde du tracé plutôt que sous le pointeur.
 */

const PALETTE = ["#E8F0EA", "#A7CEB8", "#5DA281", "#2C7253", "#12462E"];

// Couleurs de l'infobulle, posées en style plutôt qu'en classes : elle
// doit rester lisible même si la palette Tailwind change de noms.
const ENCRE = "#13261F";
const PAPIER = "#F3F4F1";

// Au-delà de cette fraction de la largeur, l'infobulle passe à gauche du
// pointeur pour ne pas sortir du cadre.
const BASCULE = 0.66;

function normaliser(s) {
  return String(s || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

export default function Carte({ lignes, unite, meta }) {
  const [geo, setGeo] = useState(null);
  const [erreur, setErreur] = useState(null);
  const [survol, setSurvol] = useState(null);
  const [bulle, setBulle] = useState(null);
  const cadre = useRef(null);

  useEffect(() => {
    getGeo().then(setGeo).catch((e) => setErreur(e.message));
  }, []);

  const parZone = useMemo(() => {
    const m = new Map();
    for (const l of lignes || []) {
      if (l.geojson_id) m.set(normaliser(l.geojson_id), l);
      if (l.zone) m.set(normaliser(l.zone), l);
    }
    return m;
  }, [lignes]);

  // Cinq classes par rangs plutôt que par intervalles égaux : la
  // population sénégalaise est très concentrée sur Dakar, et un découpage
  // linéaire y écraserait treize régions dans la classe la plus claire.
  const seuils = useMemo(() => {
    const vals = (lignes || [])
      .map((l) => Number(l.valeur))
      .filter((v) => !Number.isNaN(v))
      .sort((a, b) => a - b);
    if (!vals.length) return [];
    return [0.2, 0.4, 0.6, 0.8].map(
      (q) => vals[Math.floor(q * (vals.length - 1))],
    );
  }, [lignes]);

  const couleur = (v) => {
    if (v === null || v === undefined) return "#EDEFEC";
    let i = 0;
    while (i < seuils.length && Number(v) > seuils[i]) i += 1;
    return PALETTE[i];
  };

  const { chemin, traits } = useMemo(() => {
    if (!geo?.features?.length) return { chemin: null, traits: [] };
    const projection = geoMercator().fitExtent(
      [
        [12, 12],
        [668, 468],
      ],
      geo,
    );
    const gen = geoPath(projection);
    return {
      chemin: gen,
      traits: geo.features.map((f) => {
        const p = f.properties || {};
        const cle = normaliser(p.id || p.code || p.name || p.nom);
        const cleNom = normaliser(p.name || p.nom);
        const ligne = parZone.get(cle) || parZone.get(cleNom);
        return {
          d: gen(f),
          // Centroïde du tracé, dans le repère du viewBox. Sert à placer
          // l'infobulle quand la région reçoit le focus au clavier, sans
          // pointeur pour l'ancrer.
          centre: gen.centroid(f),
          nom: p.name || p.nom || "",
          valeur: ligne ? Number(ligne.valeur) : null,
        };
      }),
    };
  }, [geo, parZone]);

  /** Texte de l'infobulle et du relevé, identique pour les deux. */
  const lire = (t) =>
    t.valeur === null
      ? "sans donnée"
      : `${nombre(t.valeur, unite)}${fmtUnite(unite)}`;

  /** Position de l'infobulle à partir d'un évènement de souris. */
  const suivrePointeur = (t) => (e) => {
    const r = cadre.current?.getBoundingClientRect();
    if (!r) return;
    setBulle({
      x: e.clientX - r.left,
      y: e.clientY - r.top,
      largeur: r.width,
      trait: t,
    });
  };

  /**
   * Position de l'infobulle pour une région atteinte au clavier.
   *
   * Le centroïde est exprimé dans le repère du viewBox (680 × 480) : il
   * faut le ramener aux pixels réels du cadre, dont la largeur varie.
   */
  const placerAuCentre = (t) => () => {
    const r = cadre.current?.getBoundingClientRect();
    if (!r || !t.centre) return;
    const echelle = r.width / 680;
    setSurvol(t);
    setBulle({
      x: t.centre[0] * echelle,
      y: t.centre[1] * echelle,
      largeur: r.width,
      trait: t,
    });
  };

  const quitter = () => {
    setSurvol(null);
    setBulle(null);
  };

  if (erreur) {
    return (
      <div className="text-sm text-signal">
        {erreur} Les valeurs restent consultables dans le tableau ci-dessous.
      </div>
    );
  }
  if (!chemin) {
    return <div className="h-72 bg-echelle-1/40 rounded animate-pulse" />;
  }

  return (
    <figure className="m-0">
      <div className="relative" ref={cadre}>
        <svg
          viewBox="0 0 680 480"
          className="w-full h-auto"
          role="img"
          aria-label={`Carte du Sénégal : ${meta?.indicateur || "valeurs"} par région`}
          onMouseLeave={quitter}
        >
          {traits.map((t, i) => (
            <path
              key={i}
              d={t.d}
              fill={couleur(t.valeur)}
              stroke="#FFFFFF"
              strokeWidth="1"
              tabIndex={0}
              role="img"
              aria-label={`${t.nom} : ${lire(t)}`}
              onMouseEnter={() => setSurvol(t)}
              onMouseMove={suivrePointeur(t)}
              onFocus={placerAuCentre(t)}
              onBlur={quitter}
              className="cursor-default outline-none transition-opacity
                         hover:opacity-85 focus-visible:opacity-85"
              style={
                survol === t
                  ? { stroke: ENCRE, strokeWidth: 1.5 }
                  : undefined
              }
            />
          ))}
        </svg>

        {bulle && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute z-10 rounded px-2 py-1
                       text-xs whitespace-nowrap shadow-lg tabulaire"
            style={{
              left: bulle.x,
              top: bulle.y,
              background: ENCRE,
              color: PAPIER,
              // Décalage plutôt que centrage : l'infobulle ne doit jamais
              // masquer le point survolé. Elle bascule à gauche près du
              // bord droit.
              transform: `translate(${
                bulle.x > bulle.largeur * BASCULE ? "calc(-100% - 12px)" : "12px"
              }, -50%)`,
            }}
          >
            <span style={{ opacity: 0.7 }}>{bulle.trait.nom}</span>{" "}
            <span className="font-medium">{lire(bulle.trait)}</span>
          </div>
        )}
      </div>

      <figcaption className="mt-1 flex items-start justify-between gap-6 flex-wrap">
        <div className="flex items-center gap-2 text-xs text-sourdine">
          <span>{nombre(Math.min(...seuils))}</span>
          <div className="flex" aria-hidden="true">
            {PALETTE.map((c) => (
              <span
                key={c}
                className="w-7 h-3 first:rounded-l last:rounded-r"
                style={{ background: c }}
              />
            ))}
          </div>
          <span>
            {nombre(meta?.max)}
            {fmtUnite(unite)}
          </span>
        </div>

        {/* Relevé permanent : c'est lui qui est annoncé par les lecteurs
            d'écran. L'infobulle ci-dessus n'en est que le doublon
            visuel. */}
        <div className="text-sm min-h-[1.5rem] tabulaire" aria-live="polite">
          {survol && (
            <>
              <span className="text-sourdine">{survol.nom} : </span>
              <span className="font-medium">{lire(survol)}</span>
            </>
          )}
        </div>
      </figcaption>
    </figure>
  );
}