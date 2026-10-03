"""
backend/analytics/resultats.py

StatSense AI — Contrat de sortie du moteur analytique

Les quatre méthodes retournent la MÊME structure. Le frontend n'a donc
qu'un composant à écrire, qui choisit son affichage selon `chart_hint`.
Ajouter une cinquième méthode plus tard ne casse rien.

`notes` est ce qui distingue une plateforme statistique d'un tableur :
c'est là que le moteur signale la règle méthodologique appliquée
(glissement annuel, refus d'agrégation, série relayée) ou une limite des
données. Ces notes sont produites par le code, jamais par le modèle de
langage — elles sont donc toujours exactes.
"""

from dataclasses import dataclass, field
from decimal import Decimal


def _json(v):
    """Rend une valeur sérialisable, y compris dans les structures imbriquées."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    return v


class ErreurAnalyse(Exception):
    """
    Le plan est syntaxiquement valide mais inexécutable sur ces données.

    `alternatives` alimente la réponse proposée à l'utilisateur : un refus
    accompagné d'une piste vaut mieux qu'un refus sec.
    """

    def __init__(self, message, motif=None, alternatives=None):
        super().__init__(message)
        self.message = message
        self.motif = motif
        self.alternatives = alternatives or []


@dataclass
class AnalysisResult:
    lignes: list[dict] = field(default_factory=list)
    unite: str = ""
    sources: list[dict] = field(default_factory=list)
    chart_hint: str = "kpi"        # kpi | bar | line | choropleth | table
    notes: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def vide(self):
        return not self.lignes

    def to_dict(self):
        return {
            "lignes": [_json(l) for l in self.lignes],
            "unite": self.unite,
            "sources": self.sources,
            "chart_hint": self.chart_hint,
            "notes": self.notes,
            "meta": _json(self.meta),
        }


def source_de(indicateur):
    """Encart de provenance affiché sous chaque résultat."""
    s = indicateur.source
    return {
        "nom": s.nom,
        "url": s.url,
        "plateforme": s.plateforme,
        "date_extraction": str(s.date_extraction),
    }