"""
backend/analytics/avertissements.py

StatSense AI — Limites méthodologiques attachées aux données

Ce que les chiffres ne disent pas d'eux-mêmes, et qu'il serait malhonnête
de taire.

Une ventilation par âge qui ne totalise pas 100 %, une courbe construite
sur six enquêtes différentes, un total calculé par le chargement et non
publié par la source : ces faits ne se voient pas sur un graphique. Ils se
disent, ou ils induisent en erreur.

Ces notes sont produites par le CODE, jamais par le modèle de langage.
Elles sont donc toujours exactes — c'est ce qui les distingue d'une phrase
de prudence ajoutée par une IA, qui serait vraie en moyenne.


POURQUOI CE FICHIER A DÛ ÊTRE ÉCRIT

Le catalogue portait déjà ces avertissements, dans
`data/seed/catalogue_regional.py`, sous le nom AVERTISSEMENTS. Un grep l'a
montré : définis là, lus nulle part.

    data/seed/catalogue_regional.py:153:AVERTISSEMENTS = {

Du code mort, donc, et pas n'importe lequel : la pyramide des âges rendait
dix-sept tranches sans mentionner que les 60-64 ans n'y figurent pas. Le
graphique était juste, la lecture qu'il invitait à faire ne l'était pas.


OÙ CES TEXTES DEVRAIENT VIVRE

Dans le catalogue, comme `derive_de` : un champ sur le modèle
`Indicateur`, renseigné par le seed. C'est une propriété des données, pas
du moteur.

Ils sont ici en attendant, pour ne pas introduire une migration dans la
semaine du gel. La copie de `catalogue_regional.py` ne sert plus qu'au
dossier et à la documentation ; celle-ci est la seule que la plateforme
lit. Le jour où le champ existera, ce module disparaîtra.
"""

# Avertissement attaché à un indicateur, quelle que soit la question.
PAR_INDICATEUR = {
    "acces_eau": (
        "Le taux affiché sans ventilation est la somme des quatre sources "
        "améliorées — robinet dans le logement, robinet public, puits avec "
        "pompe, puits protégé — calculée au chargement ; la source ne "
        "publie pas ce total. Le puits non protégé en est exclu, n'étant "
        "pas une source améliorée."
    ),
    "indice_bienetre": (
        "Série irrégulière : onze points entre 1997 et 2023. Les écarts "
        "entre deux points ne sont pas comparables à un rythme annuel."
    ),
    "taux_natalite": (
        "Série irrégulière : dix-sept points entre 1992 et 2025."
    ),
}

# Avertissement attaché à une méthode pour un indicateur donné. Une
# évolution construite sur des enquêtes distinctes n'a pas la même valeur
# qu'une série annuelle continue, et seule l'évolution est concernée : une
# valeur ponctuelle ne compare rien.
PAR_METHODE = {
    ("acces_eau", "evolution"): (
        "Les points de cette série proviennent d'enquêtes différentes, "
        "menées à des années irrégulières. Un écart entre deux points peut "
        "refléter un changement de méthodologie d'enquête autant qu'une "
        "évolution réelle."
    ),
}

# Avertissement attaché à une dimension, dès qu'elle est employée — en
# ventilation ou en filtre.
PAR_DIMENSION = {
    "age": (
        "Les tranches d'âge publiées ne couvrent pas les 60-64 ans : une "
        "ventilation par âge ne totalise donc pas 100 %."
    ),
}


def avertissements_pour(code, methode=None, dimension=None, filtres=None):
    """
    Notes méthodologiques applicables, dans l'ordre du plus général au plus
    particulier, sans doublon.

    `dimension` et `filtres` sont traités ensemble : employer l'âge en
    ventilation ou le filtrer sur une tranche expose à la même lacune des
    données.
    """
    notes = []

    def ajouter(texte):
        if texte and texte not in notes:
            notes.append(texte)

    ajouter(PAR_INDICATEUR.get(code))
    ajouter(PAR_METHODE.get((code, methode)))

    employees = set(filtres or {})
    if dimension:
        employees.add(dimension)
    for d in sorted(employees):
        ajouter(PAR_DIMENSION.get(d))

    return notes