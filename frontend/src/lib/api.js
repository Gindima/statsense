/**
 * Accès à l'API StatSense.
 *
 * Toutes les requêtes passent par /api, relayé vers Django par le proxy
 * Vite en développement et servi par le même hôte en production.
 */

async function requete(chemin, options = {}) {
  const r = await fetch(`/api${chemin}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!r.ok && r.status >= 500) {
    throw new Error(`Le service ne répond pas (${r.status}).`);
  }
  return r.json();
}

export function poser(question, sansCache = false) {
  return requete("/ask/", {
    method: "POST",
    body: JSON.stringify({ question, sans_cache: sansCache }),
  });
}

export const getCatalogue = () => requete("/catalogue/");
export const getHistorique = () => requete("/historique/");
export const getSante = () => requete("/sante/");

export async function getGeo() {
  const r = await fetch("/api/geo/");
  if (!r.ok) throw new Error("Contours géographiques indisponibles.");
  return r.json();
}
