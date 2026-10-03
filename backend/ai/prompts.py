"""
backend/ai/prompts.py

StatSense AI — Prompts

Deux prompts seulement, correspondant aux deux moments où le modèle
intervient : traduire une question en plan, puis commenter un résultat.


L'ORDRE DES BLOCS EST DICTÉ PAR LE CACHE, PAS PAR LA LISIBILITÉ

Ollama conserve en cache le préfixe de prompt déjà évalué. Mesuré sur la
machine de développement : un prompt de 1 003 tokens coûte 69,6 s de
lecture la première fois, 0,2 s la seconde.

Tout ce qui suit le premier token modifié doit être réévalué. La liste
des indicateurs change à chaque question — elle est donc placée EN
DERNIER, juste avant la question. Les consignes et les exemples, qui ne
changent jamais, forment un préfixe stable partagé par toutes les
questions et ne sont évalués qu'une fois par démarrage du modèle.

Dans la version précédente la liste venait en tête : les 800 tokens de
consignes situés après elle étaient réévalués à chaque question, pour
rien.

Bénéfice secondaire : les modèles pondèrent davantage la fin du prompt.
Placer la liste des codes juste avant la question sert aussi la justesse
du choix.

NE PAS DÉPLACER LES BLOCS SANS REMESURER.


QUATRE PRINCIPES, TIRÉS DES ESSAIS

  1. ÉNUMÉRER LES VALEURS PERMISES. Sans liste fermée, le modèle invente
     son vocabulaire — il a produit « régionale » pour le niveau et
     « croissant » pour l'ordre, qu'aucune validation n'accepte.

  2. DONNER DES EXEMPLES. Sur un modèle de petite taille, c'est le
     meilleur rendement de toute la partie IA. Mais un exemple pèse plus
     qu'une règle : voir ci-dessous.

  3. AUTORISER L'ABSTENTION — SANS L'ENCOURAGER. Voir ci-dessous.

  4. NE DEMANDER QUE CE QU'ON UTILISE. `zones` et `periode` ont été
     retirés : chaine.py les écrase par zones.py et periodes.py. Ils
     étaient payés deux fois, en lecture et en génération, pour être
     jetés. `filtres` subsiste, parce que les ventilations que le code ne
     sait pas reconnaître — âge, secteur, quintile — restent au modèle.


POURQUOI IL N'Y A PAS D'EXEMPLE DE REFUS

Un exemple montrant `indicateur: null` a été essayé. Il a fait tomber
les refus de 100 % à 0 %, ce qui paraît absurde et ne l'est pas.

Le modèle a appris à produire une `clarification`, et dans chaine.py une
clarification court-circuitait l'exécution du moteur. « La population de
Dakar en 2010 » n'atteignait donc plus le contrôle de période et ne
produisait plus `periode_non_couverte` : un doute du modèle avait
remplacé un refus vérifiable.

Le chemin voulu est l'inverse. Le modèle nomme l'indicateur que la
question suggère, même absent du catalogue ; `_slug()` le normalise sans
le rejeter ; le moteur constate qu'il n'existe pas et refuse avec un
motif et une source. Le code inventé par le modèle devient la preuve qui
fonde un refus précis.

La règle écrite subsiste, pour le cas où le modèle choisirait de
s'abstenir. Mais aucun exemple ne l'y invite : sur un petit modèle, un
exemple pèse plus lourd qu'une règle.


LES NOMS MONTRÉS AU MODÈLE SONT DES NOMS D'API

Les ventilations étaient annoncées par `| vent:` et décrites comme
« les "vent" de l'indicateur ». Le modèle a produit
`filtres: {"dimension": …, "vent": …}` — il a pris pour des clés JSON
les mots que les guillemets désignaient comme telles. D'où deux règles :
pas d'abréviation, et pas de guillemets autour d'autre chose qu'un champ
réel du JSON.
"""

import json

SYSTEME_EXTRACTION = (
    "Tu traduis une question en plan de requête statistique. "
    "Tu ne calcules jamais et tu n'inventes aucun chiffre. "
    "Réponds UNIQUEMENT par un objet JSON, sans texte avant ni après."
)

# L'ordre des blocs est délibéré : stable d'abord, variable ensuite.
# Voir l'en-tête du module.
GABARIT_EXTRACTION = """\
Transforme la question en objet JSON décrivant l'analyse demandée.

CHAMPS
  "methode"       valeur_simple | classement | evolution | geographique | repartition
  "indicateur"    un code de la liste donnée plus bas, exactement
  "niveau"        national | region | departement | commune | quartier
  "dimension"     pour une repartition : la ventilation à décomposer, prise
                  dans les ventilations listées pour l'indicateur
  "filtres"       ventilation à appliquer, prise dans les ventilations listées
                  pour l'indicateur. N'indique jamais le sexe ni le milieu de
                  résidence : ils sont reconnus ailleurs. Exemple : {{"age": "Y15T24"}}
  "top_n"         nombre d'éléments d'un classement
  "ordre"         desc | asc
  "confiance"     0.0 à 1.0
  "clarification" une question courte si la demande est ambiguë

N'écris pas les champs vides, nuls ou sans objet. Ne mets ni zone ni année :
elles sont extraites de la question par ailleurs.

RÈGLES
- "methode" et "niveau" sont deux choses différentes : "geographique" est une
  méthode (afficher une carte), pas un niveau.
- "les plus" -> "desc". "les moins" -> "asc".
- évolution, progression, tendance -> "evolution".
- carte -> "geographique".
- une seule valeur pour un lieu précis -> "valeur_simple".
- répartition, structure, décomposition, part de chaque catégorie,
  pyramide -> "repartition".
- nomme toujours l'indicateur que la question appelle, même si aucun code de
  la liste ne lui correspond exactement : la disponibilité est vérifiée
  ensuite. Ne mets "indicateur": null que si la question ne désigne aucune
  grandeur statistique.

EXEMPLES

Q : Quelles sont les 5 régions les plus peuplées ?
{{"methode":"classement","indicateur":"pop_totale","niveau":"region","top_n":5,"ordre":"desc","confiance":0.95}}

Q : Combien d'habitants compte Thiès ?
{{"methode":"valeur_simple","indicateur":"pop_totale","niveau":"region","confiance":0.95}}

Q : Montre-moi l'accès à l'électricité sur une carte
{{"methode":"geographique","indicateur":"acces_electricite","niveau":"region","confiance":0.9}}

Q : Quelle est la répartition de la population par âge ?
{{"methode":"repartition","indicateur":"pop_region","niveau":"national","dimension":"age","confiance":0.9}}

Q : Comment le chômage a-t-il évolué au Sénégal ?
{{"methode":"evolution","indicateur":"taux_chomage_a","niveau":"national","confiance":0.9}}

Q : Où les ménages sont-ils les plus grands ?
{{"methode":"classement","indicateur":"taille_menage","niveau":"region","top_n":10,"ordre":"desc","confiance":0.9}}

INDICATEURS (choisis un code dans cette liste, jamais autre chose)
{fiches}

QUESTION
{question}
"""

GABARIT_CORRECTION = """\
Le plan précédent a été rejeté : {erreur}

Corrige-le en respectant strictement les valeurs autorisées et les
indicateurs listés. Réponds uniquement par le JSON corrigé.

Question : {question}
Plan rejeté : {plan}
"""


SYSTEME_NARRATION = (
    "Tu commentes des résultats statistiques déjà calculés. "
    "Tu n'utilises AUCUN chiffre absent du tableau fourni. "
    "Tu écris en français, trois phrases maximum, sans introduction."
)

GABARIT_NARRATION = """\
Commente ces résultats en trois phrases maximum.

Question posée : {question}
Indicateur : {indicateur}
Unité : {unite}

Résultats calculés :
{lignes}

{meta}
{notes}

CONSIGNES
- N'écris que des nombres présents ci-dessus.
- Reprends les avertissements méthodologiques s'il y en a.
- Pas de formule d'introduction, va droit au constat.
"""


def _ventilations(fiche):
    """
    Dimensions de l'indicateur, en une chaîne courte.

    Le sexe et le milieu sont retirés de la liste montrée au modèle : ils
    sont reconnus par filtres.py, et les laisser visibles l'incite à les
    renseigner alors que sa réponse serait écrasée.
    """
    d = fiche.get("dimensions")
    if isinstance(d, dict):
        noms = list(d.keys())
    elif isinstance(d, (list, tuple)):
        noms = [str(x) for x in d]
    else:
        noms = []
    noms = [n for n in noms if n not in ("sexe", "milieu")]
    return ", ".join(noms[:4])


def prompt_extraction(question, fiches_indicateurs, zones=None):
    """
    Construit le prompt d'extraction.

    `zones` est accepté pour compatibilité avec les appels existants mais
    n'est plus injecté : les zones sont reconnues par zones.py, et la
    liste des régions dans le prompt ne servait qu'à faire recopier au
    modèle celles des exemples.
    """
    lignes = []
    for f in fiches_indicateurs:
        ligne = (f"- {f['code']} : {f['libelle']} ({f['unite']})"
                 f" | {f['niveau_min']} | {f['periodes']}")
        vent = _ventilations(f)
        if vent:
            ligne += f" | ventilations : {vent}"
        lignes.append(ligne)

    return GABARIT_EXTRACTION.format(
        fiches="\n".join(lignes),
        question=question.strip(),
    )


def prompt_correction(question, plan, erreur):
    return GABARIT_CORRECTION.format(
        erreur=erreur,
        question=question.strip(),
        plan=json.dumps(plan, ensure_ascii=False),
    )


def prompt_narration(question, resultat):
    lignes = resultat.lignes[:25]
    corps = "\n".join(
        "  " + " | ".join(f"{k}={v}" for k, v in l.items()
                          if k not in ("code", "geojson_id"))
        for l in lignes
    )
    if len(resultat.lignes) > 25:
        corps += f"\n  (… {len(resultat.lignes) - 25} ligne(s) de plus)"

    infos = []
    m = resultat.meta or {}
    for cle, libelle in (("variation_pct", "variation en %"),
                         ("tcam_pct", "croissance annuelle moyenne en %"),
                         ("debut", "première période"),
                         ("fin", "dernière période"),
                         ("periode", "période")):
        if m.get(cle) is not None:
            v = m[cle]
            if isinstance(v, (int, float)) or hasattr(v, "quantize"):
                v = f"{float(v):.2f}"
            infos.append(f"  {libelle} : {v}")

    notes = ""
    if resultat.notes:
        notes = "Avertissements à reprendre :\n" + "\n".join(
            f"  - {n}" for n in resultat.notes)

    return GABARIT_NARRATION.format(
        question=question.strip(),
        indicateur=m.get("indicateur", ""),
        unite=resultat.unite,
        lignes=corps,
        meta="\n".join(infos),
        notes=notes,
    )