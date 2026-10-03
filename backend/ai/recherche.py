"""
backend/ai/recherche.py

StatSense AI — Sélection des indicateurs présentés au modèle

Le catalogue n'est pas envoyé en entier. La raison est mesurée.

Sur la machine de développement — 4 cœurs, pas de carte graphique — le
modèle lit environ 16 tokens par seconde. Les seize fiches du catalogue
portaient le prompt à 1 627 tokens, soit 117 secondes de lecture avant
que le modèle n'écrive quoi que ce soit. À six fiches, le prompt tombe
à ~1 000 tokens et la lecture à 70 secondes, sans que l'indicateur choisi
change. À trois fiches il n'y a plus de gain de lecture — les fiches ne
pèsent que 400 tokens sur 1 627 — et le modèle commence à inventer des
codes par analogie (`taux_natalite_a` pour `taux_natalite`).

Six est donc le point où la latence a fini de baisser et où la justesse
n'a pas encore bougé.

Ce que ça coûte : dix indicateurs sont invisibles pour une question
donnée. Le risque serait réel avec un appariement approximatif ; il est
faible avec word_similarity, qui donne 1.0 à tout mot figurant dans la
fiche. Un indicateur absent du sextuor de tête est un indicateur dont la
question n'emploie aucun mot — cas où il n'aurait pas été choisi de
toute façon.


UNE VENTILATION DÉCLARÉE REND L'INDICATEUR TROUVABLE

L'affirmation ci-dessus avait une faille, constatée sur « Combien de
femmes à Dakar ? » :

    scores    : rapport_masculinite 1.000, taux_chomage_a 1.000
    présentés : rapport_masculinite, taux_chomage_a, concessions, menages

`pop_totale` n'était pas mal classé : il était absent. Les deux seuls
mots utiles sont « femmes » et « dakar » ; « dakar » est une zone et ne
matche aucune fiche ; « femmes » figure dans les synonymes de
`rapport_masculinite` et dans ceux du chômage, mais nulle part dans la
fiche de `pop_totale` — qui déclare pourtant `sexe` parmi ses dimensions.

Un indicateur ventilable par sexe n'était donc pas trouvable par le
vocabulaire du sexe. Aucun départage ne pouvait corriger cela : le tri
n'ordonne que ce qui a passé le seuil.

La règle ajoutée est fermée et vérifiable : si un mot de la question
nomme une modalité d'une dimension, les indicateurs qui DÉCLARENT cette
dimension deviennent candidats. Pas ceux qui ne la déclarent pas — c'est
ce qui préserve les refus : « ménages dirigés par une femme » ne fait pas
entrer `menages` par cette porte, puisqu'il n'est pas ventilé par sexe,
et le moteur continue de refuser.

Le vocabulaire n'est pas redéfini ici. C'est la table MOTS de
`filtres.py`, qui sert déjà à poser les filtres : les deux usages lisent
la même liste, et un mot ajouté là profite aux deux. Seuls les motifs
d'un seul mot sont retenus, puisque l'appariement se fait mot à mot.

Ce chemin donne 1.0, comme un synonyme exact. Il met l'indicateur dans
les candidats ; il ne décide pas à la place du modèle.


TROIS DÉPARTAGES, DU PLUS PARLANT AU PLUS ARBITRAIRE

word_similarity sature : elle rend 1.000 dès qu'un mot de la question
figure dans la fiche. Les égalités sont donc la règle, pas l'exception,
et c'est le départage qui décide réellement de ce que le modèle voit.

Trois critères, dans cet ordre.

1. Le nombre de mots reconnus — la spécificité

   Un indicateur qui répond à deux mots de la question est plus
   probablement le bon que celui qui n'en reconnaît qu'un.

       « quelle est la population de Dakar »
          part_population : 1 mot  (population)
          pop_totale      : 1 mot  (population)      -> égalité

       « quelle est la part de Dakar dans la population »
          part_population : 2 mots (part, population) -> gagne
          pop_totale      : 1 mot  (population)

   C'est le critère qui manquait : `part_population` arrivait en tête de
   toute question contenant le mot « population », y compris celles qui
   ne demandaient aucune proportion.

2. L'indicateur de base avant l'indicateur dérivé

   Un indicateur dérivé possède dans sa fiche les mots de son opération
   — « part », « taille », « rapport ». Si la question les emploie, il
   gagne déjà par le critère précédent. Si elle ne les emploie pas,
   l'égalité porte sur les seuls mots de la base, et c'est la base que la
   question désigne. `derive_de` est déjà en base : aucune liste codée en
   dur.

3. La granularité la plus fine

   Le moteur sait agréger, il ne sait pas désagréger. Un indicateur
   publié au quartier répond à une question régionale par somme des
   descendants ; un indicateur publié à la région refuse une question
   départementale, et il a raison de refuser. À tout le reste égal, le
   plus fin couvre donc le plus de questions. C'est ce qui résout
   `pop_totale` (quartier) contre `pop_region` (département) en faveur du
   recensement.

Le code vient en dernier pour rendre le tri total, donc l'ordre
reproductible — condition pour qu'un test qui passe passe toujours.

Ce départage n'est qu'un ordre de présentation. Ce qui permet au modèle
de distinguer réellement deux séries proches, ce sont leurs libellés —
« Population recensée (RGPH-5, 2023) » contre « Population projetée » —
et c'est au catalogue de les porter.


MESURE DE PROXIMITÉ — pourquoi word_similarity et non similarity

similarity(fiche, mot) est SYMÉTRIQUE : elle divise les trigrammes
communs par le total des trigrammes des deux chaînes. Un mot de huit
lettres comparé à une fiche de deux cents caractères plafonne donc très
bas — mesuré à 0,095 — même quand le mot figure mot pour mot dans les
synonymes. Deux conséquences constatées : « les régions les plus
peuplées » échouait alors que « peuplées » était un synonyme déclaré, et
enrichir un indicateur le rendait MOINS trouvable, puisque chaque
synonyme ajouté allongeait le dénominateur.

word_similarity(mot, fiche) est ASYMÉTRIQUE : elle cherche dans la fiche
le meilleur fragment aligné sur des frontières de mots et ne note que
celui-là. La longueur de la fiche cesse de compter. Mesuré sur les
mêmes données : 1.000 pour un synonyme exact, 0,40 à 0,43 pour un mot
étranger au domaine.

Sa limite est la saturation décrite plus haut. Une mesure qui la
corrigerait à la racine consisterait à inverser le sens — chercher le
synonyme dans la question plutôt que le mot de la question dans la fiche
—, ce qui récompenserait la spécificité au lieu de la reconstituer par le
comptage. C'est la bonne réponse de fond, et c'est une réécriture de
`scores()` : à réserver pour une version ultérieure, mesures à l'appui.

Les accents sont retirés des deux côtés : la question en Python,
la fiche par translate() en SQL. translate() est préféré à unaccent()
pour ne dépendre d'aucune extension au-delà de pg_trgm.
"""

import re
import unicodedata

from django.db.models import FloatField, Func, TextField, Value
from django.db.models.functions import Concat, Lower

from ai.filtres import MOTS
from catalog.models import Indicateur

# Nombre d'indicateurs jusqu'auquel le catalogue est envoyé en entier.
# Fixé à 6 après mesure : au-delà, la lecture du prompt domine la latence
# sans que la justesse y gagne.
CATALOGUE_COMPLET_MAX = 6

# Nombre de candidats retenus quand une présélection est nécessaire.
N_CANDIDATS = 6

# Plancher de similarité. Avec word_similarity, un mot sans rapport avec
# le domaine reste sous 0,45 ; une variante reconnaissable dépasse 0,55.
# Vérifiable avec tests/calibrer.py.
SEUIL = 0.50

# Granularité géographique, du plus large au plus fin. Dernier départage
# avant le code : le plus fin peut être agrégé vers le plus large,
# l'inverse est impossible.
FINESSE = {
    "national": 0,
    "region": 1,
    "departement": 2,
    "commune": 3,
    "quartier": 4,
}

# Table de translittération pour translate(). Les deux chaînes doivent
# avoir exactement le même nombre de caractères, et refléter ce que fait
# _sans_accents() côté Python.
ACCENTS = "àâäáãåçéèêëíìîïñòóôöõùúûüýÿ"
SANS_ACCENTS = "aaaaaaceeeeiiiinooooouuuuyy"

# Mots vides : n'apportent rien à l'appariement.
VIDES = {
    "le", "la", "les", "un", "une", "des", "du", "de", "d", "l",
    "quel", "quelle", "quels", "quelles", "est", "sont", "combien",
    "y", "a", "t", "il", "en", "au", "aux", "dans", "pour", "par",
    "sur", "avec", "que", "qui", "quoi", "ou", "et", "me", "moi",
    "donne", "montre", "affiche", "liste", "cherche", "trouve",
    "je", "veux", "voudrais", "peux", "tu", "vous", "s", "ce", "cette",
    "comment", "pourquoi", "quand", "plus", "moins", "region", "regions",
    "departement", "departements", "carte", "graphique", "svp",
}


def _vocabulaire_dimension():
    """
    mot -> dimension, construit depuis la table MOTS de filtres.py.

    Seuls les motifs d'un seul mot sont retenus : l'appariement de
    scores() se fait mot à mot, une locution comme « en ville » n'y
    arriverait jamais. Les motifs y sont déjà sans accents, comme les
    mots de la question.
    """
    out = {}
    for motifs, (cle, _valeur) in MOTS:
        for m in motifs:
            if " " not in m:
                out[m] = cle
    return out


VOCABULAIRE_DIMENSION = _vocabulaire_dimension()


class SynonymesTexte(Func):
    """
    array_to_string(synonymes, ' ') — aplatit le tableau pour que la
    similarité porte aussi sur les synonymes, qui font l'essentiel de
    l'appariement : un utilisateur écrit « combien de gens », jamais
    « population totale résidente ».
    """

    function = "array_to_string"
    output_field = TextField()

    def __init__(self, expression, separateur=" ", **extra):
        super().__init__(expression, Value(separateur), **extra)


class SansAccents(Func):
    """
    translate(texte, 'àâä…', 'aaa…') — aligne la fiche sur la question,
    qui arrive déjà sans accents. Sans cela « peuplees » ne rencontre
    jamais « peuplées ».
    """

    function = "translate"
    output_field = TextField()

    def __init__(self, expression, **extra):
        super().__init__(expression, Value(ACCENTS), Value(SANS_ACCENTS),
                         **extra)


class MotSimilaire(Func):
    """
    word_similarity(mot, fiche) — proximité du mot au meilleur fragment
    de la fiche, indépendante de la longueur de celle-ci.

    L'ordre des arguments compte et n'est pas celui de similarity() :
    le mot cherché vient EN PREMIER, la fiche ensuite.
    """

    function = "word_similarity"
    output_field = FloatField()


def _sans_accents(s):
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def mots_utiles(question):
    """
    Ne garde que les mots porteurs de sens.

    Filet de sécurité : certaines questions se réduisent à un seul mot
    utile — « Quelles sont les 5 régions les plus peuplées ? » ne laisse
    que « peuplees », le reste étant vide ou trop court. Si le filtrage
    ne laisse rien du tout, on repart des mots bruts plutôt que de
    rendre une liste vide, qui ferait échouer l'appariement sur une
    question pourtant légitime.
    """
    s = _sans_accents(question).lower()
    mots = re.findall(r"[a-z0-9']+", s)
    utiles = [m for m in mots if m not in VIDES and len(m) > 2]
    if utiles:
        return utiles
    return [m for m in mots if len(m) > 2]


def _texte_indicateur():
    """Fiche de l'indicateur, minuscules et sans accents."""
    return SansAccents(
        Lower(
            Concat("libelle", Value(" "), "code", Value(" "),
                   SynonymesTexte("synonymes"), output_field=TextField())
        )
    )


def _codes_par_dimension():
    """
    dimension -> codes des indicateurs qui la déclarent.

    Une seule requête, relue à chaque appel : le catalogue tient en seize
    lignes, et un cache de module se désynchroniserait du jour où l'on
    recharge les indicateurs sans redémarrer.
    """
    out = {}
    for code, dims in Indicateur.objects.values_list("code", "dimensions"):
        for d in dims or []:
            out.setdefault(d, []).append(code)
    return out


def apparier(question):
    """
    Pour chaque indicateur : son meilleur score, et le nombre de mots de
    la question auxquels il répond.

    La mesure porte sur chaque mot séparément plutôt que sur la phrase
    entière : une question contient des mots de liaison et des mots de
    zone qui n'ont aucun équivalent dans le catalogue, et qui n'ont donc
    pas à peser sur le score.

    Deux chemins mènent à un appariement, et le meilleur score des deux
    l'emporte :

      - le mot ressemble à la fiche (libellé, code, synonymes) ;
      - le mot nomme une modalité d'une dimension que l'indicateur
        déclare ventilable.

    Le second rattrape ce que le premier ne peut pas voir : « femmes »
    n'apparaît pas dans la fiche de `pop_totale`, mais `pop_totale` est
    ventilé par sexe et sait donc répondre.

    Le comptage des mots est ce qui permet de départager les égalités de
    score, systématiques avec word_similarity. Un mot compte une fois,
    quel que soit le chemin par lequel il a apparié.

    Retourne {code: (score, nombre_de_mots)}.
    """
    meilleur, comptes = {}, {}
    par_dimension = None

    for mot in mots_utiles(question):
        apparies = {}

        dim = VOCABULAIRE_DIMENSION.get(mot)
        if dim:
            if par_dimension is None:
                par_dimension = _codes_par_dimension()
            for code in par_dimension.get(dim, ()):
                apparies[code] = 1.0

        lignes = (
            Indicateur.objects
            .annotate(texte=_texte_indicateur())
            .annotate(score=MotSimilaire(Value(mot), "texte"))
            .filter(score__gte=SEUIL)
            .values_list("code", "score")
        )
        for code, s in lignes:
            apparies[code] = max(apparies.get(code, 0.0), float(s))

        for code, s in apparies.items():
            meilleur[code] = max(meilleur.get(code, 0.0), s)
            comptes[code] = comptes.get(code, 0) + 1

    return {code: (s, comptes[code]) for code, s in meilleur.items()}


def scores(question):
    """
    Proximité de chaque indicateur avec la question, par son meilleur
    mot. Conservé pour les appels et les tests existants.
    """
    return {code: s for code, (s, _n) in apparier(question).items()}


def _rang(indicateur, classement):
    """
    Clé de tri, du critère le plus parlant au plus arbitraire : score,
    nombre de mots reconnus, base avant dérivé, granularité la plus fine,
    code.

    Les trois critères intermédiaires existent parce que word_similarity
    sature à 1.000 : sans eux, l'ordre réel serait alphabétique.
    """
    score, mots = classement.get(indicateur.code, (0.0, 0))
    return (
        -score,
        -mots,
        1 if indicateur.derive_de else 0,
        -FINESSE.get(indicateur.granularite_geo_min, 0),
        indicateur.code,
    )


def rechercher(question, n=N_CANDIDATS):
    """
    Indicateurs à présenter au modèle, les plus probables en tête.

    Retourne le catalogue entier tant qu'il tient dans le prompt ; au-delà,
    les n premiers d'un tri total.
    """
    tous = list(Indicateur.objects.select_related("source"))
    if not tous:
        return []

    classement = apparier(question)
    ordonnes = sorted(tous, key=lambda i: _rang(i, classement))

    if len(tous) <= CATALOGUE_COMPLET_MAX:
        return ordonnes
    return ordonnes[:n]


def fiches(indicateurs):
    """
    Métadonnées injectées dans le prompt. AUCUNE valeur chiffrée : le
    modèle ne sait pas combien d'habitants compte Dakar, et n'a pas à le
    savoir pour comprendre la question.
    """
    from observations.models import Observation

    out = []
    for i in indicateurs:
        periodes = sorted(
            Observation.objects.filter(indicateur=i)
            .values_list("periode", flat=True).distinct()
        )
        if not periodes and i.derive_de:
            # Un indicateur dérivé n'a pas d'observation propre : ses
            # périodes sont celles de son premier composant.
            base = i.derive_de.split("/")[0].split("[")[0].strip()
            periodes = sorted(
                Observation.objects.filter(indicateur__code=base)
                .values_list("periode", flat=True).distinct()
            )
        out.append({
            "code": i.code,
            "libelle": i.libelle,
            "synonymes": i.synonymes[:6],
            "unite": i.unite,
            "dimensions": i.dimensions,
            "niveau_min": i.granularite_geo_min,
            "periodes": f"{periodes[0]} à {periodes[-1]}" if periodes
                        else "aucune",
        })
    return out


def zones_connues(limite=20):
    """
    Quelques noms de zones.

    Conservé pour les appels existants, mais le prompt d'extraction ne
    s'en sert plus : les zones sont reconnues par zones.py, et les voir
    dans le prompt incitait le modèle à recopier celles des exemples.
    """
    from geography.models import Niveau, Zone

    return list(
        Zone.objects.filter(niveau=Niveau.REGION)
        .order_by("nom").values_list("nom", flat=True)
    )[:limite]