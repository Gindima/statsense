"""
tests/prioritaires.py

StatSense AI — Les quinze questions à passer avant le gel

Chaque ligne porte la question et ce qu'on attend d'elle. L'attente n'est
pas vérifiée automatiquement : plusieurs de ces cas n'ont pas de bonne
réponse unique (quelle série de population pour 2020 ? un refus ou une
agrégation pour Mbour ?), et un test qui trancherait à ma place
masquerait justement ce qu'on veut regarder.

Ce que le script garantit, c'est que les quinze passent dans le même
ordre, que le plan retenu soit lisible d'un coup d'œil, et que l'attente
soit écrite à côté du résultat pour que l'écart saute aux yeux.

    backend/.venv/bin/python backend/manage.py shell < tests/prioritaires.py

Compter environ sept minutes : le cache de réponses couvre les questions
déjà vues, pas les nouvelles.
"""

import time

from ai import chaine

# Le nom de l'entrée a changé une fois ; on le retrouve plutôt que de le
# figer, pour qu'un renommage ne casse pas le test.
ENTREE = None
for nom in ("repondre", "traiter", "poser", "executer", "run", "chaine"):
    if callable(getattr(chaine, nom, None)):
        ENTREE = getattr(chaine, nom)
        break
if ENTREE is None:
    raise SystemExit(
        "Aucune entrée trouvée dans ai.chaine — fonctions publiques : "
        + ", ".join(n for n in dir(chaine) if not n.startswith("_"))
    )

CAS = [
    ("Combien de femmes vivent à Dakar ?",
     "pop_totale + filtre sexe=F"),
    ("Y a-t-il plus d'hommes que de femmes à Dakar ?",
     "rapport_masculinite, SANS filtre sexe"),
    ("Combien de ménages dirigés par une femme à Dakar ?",
     "refus : menages n'est pas ventilé par sexe"),
    ("Quelle est la population de Dakar en 2023 ?",
     "pop_totale (recensement)"),
    ("Quelle était la population de Dakar en 2020 ?",
     "pop_region (projections) — 2020 absent du RGPH"),
    ("Quelle était la population de Dakar en 2010 ?",
     "refus : aucune série ne couvre 2010"),
    ("Comment la population de Dakar a-t-elle évolué depuis 2016 ?",
     "evolution sur pop_region, 2016 à 2025"),
    ("Quel est le taux de chômage à Dakar ?",
     "taux_chomage_a, niveau region"),
    ("Quel est le taux de chômage à Mbour ?",
     "refus : chômage publié à la région, Mbour est un département"),
    ("Comment le chômage à Dakar a-t-il évolué depuis 2015 ?",
     "evolution, 2015 à 2025"),
    ("Quelle région a le taux de chômage le plus élevé ?",
     "classement desc, top 1, niveau region"),
    ("Quel est le PIB du Sénégal ?",
     "refus : hors catalogue"),
    ("Quel est le taux d'inflation au Sénégal ?",
     "refus : hors catalogue"),
    ("Quand a eu lieu le dernier recensement ?",
     "question documentaire, pas statistique"),
    ("Quelle est la différence entre population recensée et "
     "population projetée ?",
     "question documentaire ou clarification entre deux indicateurs"),
    ("Combien d'hommes vivent à Dakar ?",
     "pop_totale + sexe=H — 2 018 759 (correctif #4)"),
    ("Quelle est la population de Yoff ?",
     "commune YOFF — 119 351 (correctif #3)"),
    ("Quelle est la population de Touba ?",
     "commune TOUBA MOSQUEE — 1 120 824 (correctif #3)"),
    ("Quelle est la population de Paris ?",
     "refus zone_inconnue, PAS le Sénégal (correctif #3)"),
    ("Quel est le taux de chômage des femmes en 2019 ?",
     "periode fin=2019, PAS la dernière année (correctif #1)"),
]


def _plan(r):
    """Le plan en une ligne, quelle que soit la forme de la réponse."""
    p = (r or {}).get("plan") or {}
    if not p:
        return "—"
    bouts = [
        p.get("methode") or "?",
        p.get("indicateur") or "AUCUN",
    ]
    if p.get("niveau"):
        bouts.append(f"par {p['niveau']}")
    if p.get("zones"):
        bouts.append(",".join(p["zones"][:3]))
    if p.get("periode"):
        bouts.append(str(p["periode"]))
    if p.get("filtres"):
        bouts.append(
            "{" + ", ".join(f"{k}={v}" for k, v in p["filtres"].items()) + "}"
        )
    if p.get("dimension"):
        bouts.append(f"dim={p['dimension']}")
    if p.get("top_n"):
        bouts.append(f"top{p['top_n']} {p.get('ordre') or ''}".strip())
    return " · ".join(bouts)


def _issue(r):
    """Ce que le système a produit : valeur, refus, ou clarification."""
    if not isinstance(r, dict):
        return "SORTIE INATTENDUE : " + repr(r)[:120]

    if r.get("refus") or r.get("motif"):
        return "REFUS — " + str(r.get("motif") or r.get("refus"))[:140]
    if r.get("clarification"):
        return "CLARIFICATION — " + str(r["clarification"])[:140]

    res = r.get("resultat") or r.get("donnees") or {}
    lignes = res.get("lignes") if isinstance(res, dict) else None
    if lignes:
        tete = lignes[0]
        zone = tete.get("zone") or tete.get("libelle") or ""
        return (f"{len(lignes)} ligne(s) — {zone} "
                f"{tete.get('valeur')} {res.get('unite') or ''}".strip())
    if isinstance(res, dict) and res.get("valeur") is not None:
        return f"{res['valeur']} {res.get('unite') or ''}".strip()

    sources = r.get("sources") or []
    return ("aucune ligne" + (" (sans source)" if not sources else ""))


def _source(r):
    s = (r or {}).get("sources") or []
    return s[0].get("nom", "?") if s else "SOURCE ABSENTE"


print()
print("=" * 78)
print("QUINZE QUESTIONS PRIORITAIRES".center(78))
print("=" * 78)

debut = time.time()
for i, (question, attendu) in enumerate(CAS, 1):
    t0 = time.time()
    try:
        reponse = ENTREE(question)
    except Exception as e:                      # noqa: BLE001
        reponse = None
        issue = f"EXCEPTION {type(e).__name__} — {e}"
        plan = "—"
        source = "—"
    else:
        issue = _issue(reponse)
        plan = _plan(reponse)
        source = _source(reponse)
    duree = time.time() - t0

    print()
    print(f"{i:2}. {question}")
    print(f"    attendu : {attendu}")
    print(f"    plan    : {plan}")
    print(f"    obtenu  : {issue}")
    print(f"    source  : {source}    ({duree:.0f}s)")

print()
print("-" * 78)
print(f"15 questions en {time.time() - debut:.0f}s")
print()