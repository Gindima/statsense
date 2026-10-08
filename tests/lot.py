#!/usr/bin/env python
"""
tests/lot.py

StatSense AI — Passe une liste de questions dans la chaîne complète

    docker compose cp tests/. app:/app/tests/
    docker compose exec app python tests/lot.py tests/questions.txt

Une question par ligne ; les lignes vides et celles qui commencent par #
sont ignorées. Appelle repondre() directement, sans passer par l'API :
rien n'est écrit dans le cache.
"""

import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from ai.chaine import repondre  # noqa: E402


def plan_court(p):
    if not p:
        return "—"
    m = [p.get("methode") or "?", p.get("indicateur") or "AUCUN"]
    if p.get("niveau"):
        m.append(f"niveau={p['niveau']}")
    if p.get("niveau_zone"):
        m.append(f"niveau_zone={p['niveau_zone']}")
    if p.get("zones"):
        m.append("zones=" + ",".join(p["zones"]))
    per = p.get("periode") or {}
    if per.get("debut") or per.get("fin"):
        m.append(f"periode={per.get('debut')}→{per.get('fin')}")
    if p.get("filtres"):
        m.append(f"filtres={p['filtres']}")
    if p.get("dimension"):
        m.append(f"dim={p['dimension']}")
    if p.get("methode") == "classement":
        m.append(f"top{p.get('top_n')} {p.get('ordre')}")
    return " · ".join(m)


def ligne_courte(l):
    etiquette = l.get("zone") or ""
    if l.get("periode"):
        etiquette = f"{etiquette} {l['periode']}".strip()
    return f"{etiquette} = {l.get('valeur')}"


questions = [l.strip() for l in open(sys.argv[1], encoding="utf-8")
             if l.strip() and not l.lstrip().startswith("#")]

debut_total = time.time()
for i, q in enumerate(questions, 1):
    t = time.time()
    try:
        r = repondre(q)
    except Exception as e:                                  # noqa: BLE001
        print(f"\n{i:2}. {q}\n    EXCEPTION {type(e).__name__} : {e}")
        continue

    meta = r.get("meta") or {}
    print(f"\n{i:2}. {q}   ({time.time() - t:.0f}s, "
          f"origine {meta.get('origine', '?')})")
    print(f"    plan    : {plan_court(r.get('plan'))}")

    if r["statut"] == "ok":
        res = r["resultat"]
        lignes = res.get("lignes") or []
        print(f"    obtenu  : {len(lignes)} ligne(s), unité « {res.get('unite')} »")
        for l in lignes[:4]:
            print(f"              {ligne_courte(l)}")
        if len(lignes) > 4:
            print(f"              … et {len(lignes) - 4} autre(s)")
        for n in (res.get("notes") or [])[:3]:
            print(f"    note    : {n[:160]}")
    else:
        print(f"    obtenu  : {r['statut'].upper()} {r.get('motif') or ''}")
        print(f"    message : {(r.get('message') or '')[:200]}")

print(f"\n{len(questions)} questions en {time.time() - debut_total:.0f}s\n")