"""
backend/analytics/equivalences.py

StatSense AI — Séries mesurant la même grandeur par des voies différentes

Le catalogue porte deux séries de population, et c'est légitime :

    pop_totale   dénombrement du RGPH-5 : un millésime, 2023, au quartier
    pop_region   projections annuelles : 2016 à 2025, au département

Aucune n'est fausse, et aucune ne remplace l'autre. Mais chacune sait
répondre là où l'autre ne peut pas, et le modèle ne dispose d'aucun moyen
de trancher : les deux portent le mot « population ».

Constaté sur « Évolution de la population sénégalaise entre 2010 et
2025 » :

    evolution · pop_totale · national · SENEGAL · 2010 à 2025
    -> serie_trop_courte

Refus exact — un dénombrement ponctuel n'a qu'un point — et inutile,
puisque la réponse existait dans l'autre série.


POURQUOI SUBSTITUER N'EST PAS CHOISIR À LA PLACE DE L'UTILISATEUR

C'est la question qui décide si cette table est légitime.

Substituer serait abusif si les deux séries pouvaient répondre : il
faudrait alors deviner laquelle est voulue, et une demande sur « la
population en 2023 » n'a pas la même réponse selon qu'on dénombre ou
qu'on projette.

Ici le cas est l'inverse : l'indicateur retenu **ne peut pas** servir le
plan. Il n'y a pas deux possibilités à départager, il y en a une ou
aucune. Prendre la seule qui existe n'est pas un choix, c'est le seul
chemin.

Et la substitution est toujours annoncée dans les notes du résultat, avec
le motif qui l'a déclenchée. L'utilisateur voit quelle série a servi et
pourquoi l'autre ne pouvait pas.


OÙ CETTE TABLE DEVRAIT VIVRE

Dans le catalogue, comme `derive_de` : un champ `serie_equivalente` sur le
modèle `Indicateur`, renseigné par le seed. C'est la bonne place, parce
que c'est une propriété des données et non du moteur.

Elle est ici en attendant, pour ne pas introduire une migration dans la
semaine du gel. Le déplacement est mécanique : ajouter le champ, le
remplir au seed, et remplacer la lecture de EQUIVALENCES par celle de
l'attribut. Le reste du moteur ne bouge pas.
"""

# code d'indicateur -> code de la série capable de le relayer.
# La relation est déclarée dans les deux sens, parce qu'elle joue dans les
# deux : une question sur un quartier échoue sur les projections et
# réussit sur le recensement, l'inverse d'une question sur 2020.
EQUIVALENCES = {
    "pop_totale": "pop_region",
    "pop_region": "pop_totale",
}


def code_equivalent(code):
    """Code de la série de relais, ou None."""
    return EQUIVALENCES.get(code)


def serie_equivalente(code):
    """
    Indicateur de relais, chargé depuis le catalogue, ou None.

    Lecture tolérante : si le code déclaré n'existe pas en base — un
    domaine retiré, un seed partiel — on rend None et le refus d'origine
    s'applique. Une table d'équivalences périmée ne doit pas faire
    échouer une requête.
    """
    autre = code_equivalent(code)
    if not autre:
        return None
    try:
        from catalog.models import Indicateur
        return Indicateur.objects.filter(code=autre).select_related(
            "source").first()
    except Exception:
        return None