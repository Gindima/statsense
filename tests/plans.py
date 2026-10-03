"""
tests/plans.py

StatSense AI — Affiche le plan exact produit pour quelques questions

À lancer ainsi, depuis la racine du projet :

    backend/.venv/bin/python backend/manage.py shell < tests/plans.py

Ce script ne modifie rien. Pour chaque question il affiche le plan tel
qu'il arrive au moteur — après les corrections déterministes de zones.py,
filtres.py et periodes.py — puis le résultat obtenu.

Il sert à trancher trois anomalies constatées sans avoir à supposer ce
que le modèle a écrit :

  - « Taille moyenne des ménages : 0.01 personnes par ménage » est une
    valeur impossible. Il faut savoir à quel niveau géographique le
    classement a porté, et sur quelles périodes.

  - un classement qui rend 1 ligne au lieu de 10 : reste à savoir si
    top_n vaut 1 dans le plan, ou si le moteur ne rend qu'une ligne pour
    une autre raison.

  - « La ventilation ['region'] n'existe pas » : il faut voir si `region`
    arrive par `filtres` ou par `dimension`.

Le plan est la pièce à conviction. Sans lui, corriger revient à parier.
"""

import json

from ai.chaine import repondre

QUESTIONS = [
    "Où les ménages sont-ils les plus grands ?",
    "Quelles régions sont les moins peuplées ?",
    "Évolution de la population de Dakar",
    "Quelles sont les 5 régions les plus peuplées ?",
]


def main():
    for q in QUESTIONS:
        print()
        print("=" * 78)
        print(f"  {q}")
        print("=" * 78)

        try:
            r = repondre(q)
        except Exception as e:
            print(f"  exception : {type(e).__name__} : {e}")
            continue

        plan = r.get("plan") or {}
        print("  PLAN")
        print(json.dumps(plan, ensure_ascii=False, indent=2,
                         default=str))

        print(f"\n  statut : {r.get('statut')}")
        if r.get("motif"):
            print(f"  motif  : {r['motif']}")
        if r.get("message"):
            print(f"  message: {r['message']}")

        res = r.get("resultat") or {}
        lignes = res.get("lignes") or []
        print(f"  lignes : {len(lignes)}")
        for l in lignes[:4]:
            print("    " + json.dumps(l, ensure_ascii=False, default=str))

        meta = res.get("meta") or {}
        if meta:
            court = {k: v for k, v in meta.items()
                     if k not in ("geojson", "lignes")}
            print("  meta   : " + json.dumps(court, ensure_ascii=False,
                                             default=str)[:400])
        if res.get("notes"):
            print(f"  notes  : {res['notes']}")

        m = r.get("meta") or {}
        print(f"  origine: {m.get('origine')}  "
              f"tentatives: {m.get('tentatives')}  "
              f"duree: {m.get('duree_s')}s")
        if m.get("doute_modele"):
            print(f"  doute  : {m['doute_modele']}")

    print()


main()