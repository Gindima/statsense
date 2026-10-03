/**
 * Mise en forme des valeurs.
 *
 * Deux principes : l'espace insécable fine comme séparateur de milliers,
 * conformément à l'usage français, et jamais plus de décimales que
 * l'indicateur n'en porte de sens.
 */

const ESPACE = " ";

export function nombre(v, unite = "") {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);

  const decimales = Number.isInteger(n) ? 0 : unite === "%" ? 1 : 2;
  return n
    .toLocaleString("fr-FR", {
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales,
    })
    .replace(/ /g, ESPACE);
}

/** Forme abrégée pour les axes de graphique, où la place manque. */
export function compact(v) {
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1).replace(".", ",")} M`;
  if (Math.abs(n) >= 1e3) return `${Math.round(n / 1e3)}${ESPACE}k`;
  return nombre(n);
}

export function unite(u) {
  if (!u) return "";
  // Le pour-cent et le pour-mille se collent au nombre en typographie
  // française soignée ; les autres unités prennent une espace.
  return u === "%" || u === "‰" ? u : `${ESPACE}${u}`;
}

export function periode(p) {
  if (!p) return "";
  return String(p).includes("-Q") ? String(p).replace("-Q", " T") : String(p);
}
