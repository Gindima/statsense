"""
data/seed/csv_rgph.py

StatSense AI — Ingestion des CSV du RGPH 2023

Une ligne de CSV produit :
  - jusqu'à 4 Zone (région, département, commune, quartier), créées une
    fois puis réutilisées via un cache mémoire
  - 5 Observation (population totale, hommes, femmes, ménages,
    concessions)

Les indicateurs dérivés (taille des ménages, rapport de masculinité,
ménages par concession) ne sont PAS stockés : le moteur les calcule à la
volée à partir de leurs composants.


TROIS PARTICULARITÉS DES FICHIERS PUBLIÉS

1. VARIANTES D'ÉCRITURE des libellés de région et de département.
   « MALEM HODDAR » dans les CSV contre « MALEM HODAR » au référentiel,
   « KOUPENTOUM » contre « KOUMPENTOUM ». Ramenées à leur forme de
   référence par canoniser(), sans quoi un département fantôme apparaît —
   avec zéro quartier, tandis que son jumeau en porte deux cent
   vingt-huit.

2. LIGNES EN DOUBLE sous une même clé géographique. Deux cas, à ne pas
   confondre :

     - même clé ET mêmes chiffres : la ligne est répétée à l'identique,
       on l'ÉCARTE. Mesuré : 76 cas, tous dans ziguinchor.csv, soit
       27 673 habitants qui auraient été comptés deux fois.

     - même clé ET chiffres différents : deux villages réels portant le
       même nom dans la même commune, on les DISTINGUE. Mesuré : un seul
       cas, « H1 NDIAGUENE » à Darou Mouhty (Kébémer), 104 et 168
       habitants.

   La distinction se lit dans les données. Un correctif antérieur
   numérotait indistinctement toutes les répétitions : il aurait créé
   76 villages fantômes et porté le total national à 18 152 795 au lieu
   de 18 126 342.

3. TOTAUX IMPOSSIBLES. Un quartier ne peut pas compter moins d'habitants
   que de ménages. Quand c'est le cas, et que la somme des sexes est
   elle-même plausible, le total publié est une faute de saisie et non
   une donnée.

   Mesuré : une occurrence. GUINAW RAIL NORD / DAROU SALAM I, dans
   pikine.csv, porte POPULATION = 1 pour 180 ménages, 619 hommes et
   602 femmes. Un « 1 » au lieu de « 1221 ».

   Conséquence si on la laisse passer : la taille moyenne des ménages y
   vaut 1 / 180 = 0,01 personne par ménage, et ce quartier remonte dans
   les classements avec un chiffre absurde — exactement ce qu'une
   plateforme dont l'argument est l'exactitude ne peut pas afficher.

   Les trois conditions de la correction sont cumulatives et chacune est
   défendable :

     POPULATION < MENAGE          -> impossibilité, pas improbabilité
     HOMMES + FEMMES >= MENAGE    -> le remplaçant est plausible
     |HOMMES + FEMMES - POPULATION| > 1  -> ce n'est pas un arrondi

   Une simple faute de frappe sur HOMMES ne déclencherait rien : le total
   resterait supérieur au nombre de ménages.

   Chaque correction est COMPTÉE ET NOMMÉE dans le rapport de chargement.
   On ne retouche pas une donnée publiée en silence.


ÉCART RÉSIDUEL AVEC LA PUBLICATION ANSD

Avec ces trois règles, le total chargé est 18 126 342 pour 18 126 390
publiés : 48 personnes d'écart sur 18,1 millions, soit 0,0003 %.

Avant la correction du total de Pikine, l'écart était de 1 268 — dont
1 220 pour cette seule coquille de saisie.

Vérifiable à tout moment par data/seed/verifier_csv.py, qui n'écrit rien.
"""

import csv
from pathlib import Path

from catalog.models import Indicateur
from geography.models import Niveau, Zone
from observations.models import Observation

from utils import Compteur, code_zone, norm, to_decimal
from zones_sdmx import canoniser

PERIODE = "2023"

COLONNES_ATTENDUES = {
    "Region", "Departement", "COM_ARRT_VILLE", "COMMUNE",
    "QUARTIER_VILLAGE_HAMEAU", "CONCESSION", "MENAGE",
    "HOMMES", "FEMMES", "POPULATION",
}

# colonne CSV -> (code indicateur, dims)
MESURES = [
    ("POPULATION", "pop_totale", {}),
    ("HOMMES", "pop_totale", {"sexe": "H"}),
    ("FEMMES", "pop_totale", {"sexe": "F"}),
    ("MENAGE", "menages", {}),
    ("CONCESSION", "concessions", {}),
]

# Colonnes chiffrées formant la signature d'une ligne. Deux lignes de même
# clé géographique et de même signature sont la même ligne, répétée.
SIGNATURE = ("CONCESSION", "MENAGE", "HOMMES", "FEMMES", "POPULATION")

# Au-delà de cet écart, la différence entre le total et la somme des sexes
# n'est plus un arrondi.
TOLERANCE_SEXES = 1

# Sentinelle distincte de None : None signifie « hiérarchie incomplète »,
# DOUBLON signifie « ligne déjà vue à l'identique ». Les deux doivent être
# comptés séparément, l'un est une anomalie, l'autre un cas normal.
DOUBLON = object()


class ChargeurRGPH:
    """
    Le cache `self.zones` évite une requête par ligne : sur 46 fichiers
    et plus de vingt mille quartiers, c'est la différence entre quelques
    secondes et plusieurs minutes.
    """

    def __init__(self):
        self.zones = {}          # code -> Zone
        # Signatures déjà rencontrées par clé géographique, remises à zéro
        # à chaque fichier. Sert à la fois à écarter les répétitions et à
        # numéroter les homonymes réels.
        self.vues = {}           # code de base -> [signature, ...]
        self.indicateurs = {i.code: i for i in Indicateur.objects.all()}
        self._precharger_zones()

    def _precharger_zones(self):
        for z in Zone.objects.all().only("id", "code"):
            self.zones[z.code] = z

    # -- zones ------------------------------------------------------------

    def _zone(self, code, nom, niveau, parent, compteur, **extra):
        z = self.zones.get(code)
        if z is not None:
            return z
        z, cree = Zone.objects.get_or_create(
            code=code,
            defaults={"nom": norm(nom), "niveau": niveau,
                      "parent": parent, **extra},
        )
        self.zones[code] = z
        if cree:
            compteur.zones += 1
        return z

    def _hierarchie(self, ligne, compteur):
        """
        Crée ou récupère les 4 niveaux, retourne la zone la plus fine.

        Retourne None si la hiérarchie est incomplète, DOUBLON si la ligne
        a déjà été vue à l'identique.
        """
        # Région et département sont ramenés à leur libellé de référence :
        # ils servent de clé de rattachement à la hiérarchie déjà créée
        # depuis les codes SDMX. Communes et quartiers n'ont pas de
        # référentiel, leur nom est pris tel quel.
        r = canoniser(ligne["Region"])
        d = canoniser(ligne["Departement"])
        c = norm(ligne["COMMUNE"])
        q = norm(ligne["QUARTIER_VILLAGE_HAMEAU"])

        if not (r and d and c and q):
            return None

        base = code_zone(r, d, c, q)
        signature = tuple((ligne.get(col) or "").strip()
                          for col in SIGNATURE)

        vues = self.vues.setdefault(base, [])
        if signature in vues:
            # Ligne répétée à l'identique : rien à charger.
            return DOUBLON

        vues.append(signature)
        rang = len(vues)

        region = self._zone(code_zone(r), r, Niveau.REGION, None, compteur)
        dept = self._zone(code_zone(r, d), d, Niveau.DEPARTEMENT,
                          region, compteur)
        commune = self._zone(code_zone(r, d, c), c, Niveau.COMMUNE,
                             dept, compteur)

        # Homonyme réel : même clé, chiffres différents. On le numérote
        # pour qu'il reste une zone distincte, et le rang figure dans le
        # nom affiché afin que l'utilisateur voie qu'il y en a deux.
        if rang == 1:
            code_q, nom_q = base, q
        else:
            code_q, nom_q = f"{base}-{rang}", f"{q} ({rang})"
            compteur.homonymes += 1

        return self._zone(
            code_q, nom_q, Niveau.QUARTIER, commune, compteur,
            com_arrt_ville=norm(ligne.get("COM_ARRT_VILLE", "")),
        )

    # -- correction des totaux impossibles --------------------------------

    @staticmethod
    def _total_corrige(ligne):
        """
        Retourne (valeur_retenue, phrase) si le total publié est
        impossible, (None, None) sinon.

        Voir l'en-tête du module pour la justification des trois
        conditions.
        """
        h = to_decimal(ligne.get("HOMMES"))
        f = to_decimal(ligne.get("FEMMES"))
        p = to_decimal(ligne.get("POPULATION"))
        m = to_decimal(ligne.get("MENAGE"))

        if None in (h, f, p, m):
            return None, None
        if p >= m:
            return None, None                 # aucune impossibilité
        somme = h + f
        if somme < m:
            return None, None                 # le remplaçant non plus
        if abs(somme - p) <= TOLERANCE_SEXES:
            return None, None                 # simple arrondi

        phrase = (
            f"{norm(ligne.get('COMMUNE'))} / "
            f"{norm(ligne.get('QUARTIER_VILLAGE_HAMEAU'))} — "
            f"POPULATION={p} dans la source pour {m} ménages ; "
            f"retenu {somme} (somme des sexes)"
        )
        return somme, phrase

    # -- observations -----------------------------------------------------

    def _observations(self, ligne, zone, chargement, compteur):
        out = []

        corrige, phrase = self._total_corrige(ligne)
        if corrige is not None:
            compteur.correction(phrase)

        for colonne, code, dims in MESURES:
            ind = self.indicateurs.get(code)
            if ind is None:
                continue
            valeur = to_decimal(ligne.get(colonne))
            if colonne == "POPULATION" and corrige is not None:
                valeur = corrige
            if valeur is None:
                continue
            out.append(Observation(
                indicateur=ind, zone=zone, periode=PERIODE,
                dims=dims, valeur=valeur, chargement=chargement,
            ))
        return out

    # -- point d'entrée ---------------------------------------------------

    def charger(self, chemin, chargement):
        chemin = Path(chemin)
        compteur = Compteur(chemin.name)
        self.vues = {}
        lot = []

        with open(chemin, encoding="utf-8-sig", newline="") as f:
            lecteur = csv.DictReader(f)

            manquantes = COLONNES_ATTENDUES - set(lecteur.fieldnames or [])
            if manquantes:
                raise ValueError(
                    f"{chemin.name} : colonnes manquantes {sorted(manquantes)}"
                )

            for n, ligne in enumerate(lecteur, start=2):
                compteur.lignes += 1
                try:
                    zone = self._hierarchie(ligne, compteur)
                    if zone is DOUBLON:
                        compteur.doublons += 1
                        continue
                    if zone is None:
                        compteur.erreur(n, "hiérarchie géographique incomplète")
                        continue
                    lot.extend(self._observations(ligne, zone,
                                                  chargement, compteur))
                except Exception as e:
                    compteur.erreur(n, str(e))

                if len(lot) >= 1000:
                    compteur.observations += self._ecrire(lot, compteur)
                    lot = []

        if lot:
            compteur.observations += self._ecrire(lot, compteur)

        return compteur

    @staticmethod
    def _ecrire(lot, compteur):
        """
        `ignore_conflicts` reste une ceinture, mais ne devrait plus rien
        rejeter : les répétitions sont écartées avant d'arriver ici. Une
        valeur non nulle dans `ignorees` signale donc un cas non prévu —
        par exemple un rechargement sans purge — et non un défaut des
        données.
        """
        avant = Observation.objects.count()
        Observation.objects.bulk_create(lot, batch_size=1000,
                                        ignore_conflicts=True)
        ecrites = Observation.objects.count() - avant
        compteur.ignorees += len(lot) - ecrites
        return ecrites


def fichiers_rgph(racine="data/raw/rgph2023"):
    return sorted(Path(racine).glob("*.csv"))