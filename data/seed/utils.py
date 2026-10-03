"""
data/seed/utils.py

StatSense AI — Utilitaires d'ingestion
"""

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation


def norm(s):
    """
    Normalise un libellé géographique pour la comparaison.

    NFD décompose les caractères accentués en lettre de base + accent ;
    la catégorie Mn (Mark, nonspacing) désigne les accents, qu'on retire.

        norm("Thiès")     -> "THIES"
        norm("Kédougou")  -> "KEDOUGOU"
        norm(" dakar  ")  -> "DAKAR"

    Appliqué UNE SEULE FOIS, à l'ingestion. Les jointures ultérieures se
    font sur `Zone.code` ou `Zone.geojson_id`, jamais sur le nom.
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s.upper().strip()


def slug_zone(s):
    """Fragment de code : alphanumérique et tirets uniquement."""
    s = norm(s)
    # Les apostrophes (droite, typographique, accent grave) ne doivent pas
    # devenir un séparateur : « M'BACKE » et « MBACKE » désignent le même
    # département. Idem pour les traits d'union internes.
    s = re.sub(r"['’`´]", "", s)
    return re.sub(r"[^A-Z0-9]+", "-", s).strip("-")


def code_zone(*parts):
    """
    Code hiérarchique stable.

        code_zone("DAKAR", "DAKAR", "GOREE", "MBAMBARA")
        -> "SN-DAKAR-DAKAR-GOREE-MBAMBARA"

    Stable entre deux chargements : c'est ce qui rend le seed idempotent
    et permet `Zone.descendants()` par simple préfixe.
    """
    return "-".join(["SN"] + [slug_zone(p) for p in parts if p])


def empreinte(chemin):
    """sha256 du contenu d'un fichier, pour détecter les modifications."""
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(65536), b""):
            h.update(bloc)
    return h.hexdigest()


def to_decimal(v):
    """
    Convertit une valeur brute en Decimal, ou None si inexploitable.

    Gère les séparateurs de milliers (espaces fines, insécables) et la
    virgule décimale française. Retourne None plutôt que 0 : une donnée
    manquante n'est pas un zéro.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in {"-", "--", "n/a", "N/A", "ND", "..."}:
        return None
    s = s.replace(" ", "").replace(" ", "").replace(" ", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


class Compteur:
    """
    Suivi d'un chargement de fichier, pour un rapport lisible.

    Quatre compteurs, quatre natures de fait. Les confondre a coûté deux
    semaines de diagnostic erroné : le rapport annonçait des observations
    « ignorées », et l'on en a déduit que des villages homonymes
    s'écrasaient, alors qu'un fichier contenait simplement des lignes
    répétées.

      doublons     lignes identiques en tout point à une précédente.
                   Écartées. Cas normal, sans conséquence.

      homonymes    même clé géographique, chiffres différents : deux
                   villages réels portant le même nom. Numérotés et
                   conservés tous les deux.

      corrections  totaux incohérents au point d'être impossibles, et
                   remplacés. Chacune est détaillée dans le rapport :
                   on ne retouche pas une donnée publiée en silence.

      ignorees     observations refusées à l'écriture. Ne devrait plus
                   jamais arriver ; une valeur non nulle signale un cas
                   non prévu, et non un défaut des données.
    """

    def __init__(self, fichier):
        self.fichier = fichier
        self.lignes = 0
        self.zones = 0
        self.observations = 0
        self.ignorees = 0
        self.doublons = 0
        self.homonymes = 0
        self.corrections = 0
        self.details_corrections = []
        self.erreurs = []

    def erreur(self, ligne, message):
        self.erreurs.append(f"    ligne {ligne} : {message}")

    def correction(self, detail):
        """`detail` est une phrase prête à afficher."""
        self.corrections += 1
        self.details_corrections.append(detail)

    def ligne_rapport(self):
        base = (f"  ✓ {self.fichier:32} {self.lignes:5} lignes → "
                f"{self.observations:6} obs.")
        details = []
        if self.doublons:
            details.append(f"{self.doublons} doublon(s) écarté(s)")
        if self.homonymes:
            details.append(f"{self.homonymes} homonyme(s) distingué(s)")
        if self.corrections:
            details.append(f"{self.corrections} total/totaux corrigé(s)")
        if self.ignorees:
            base = base.replace("✓", "⚠")
            details.append(f"{self.ignorees} obs. rejetées à l'écriture")
        if details:
            base += "  (" + ", ".join(details) + ")"
        if self.erreurs:
            base += f"  [{len(self.erreurs)} erreurs]"

        # Les corrections sont nommées sous la ligne de rapport : une
        # donnée publiée que l'on remplace doit être traçable dans le
        # journal de chargement, y compris dans un journal de conteneur.
        for d in self.details_corrections:
            base += f"\n      ⓘ correction : {d}"
        return base