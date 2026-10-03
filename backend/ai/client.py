"""
backend/ai/client.py

StatSense AI — Client du modèle de langage

Isolé derrière une interface pour deux raisons :

  - permettre de changer de modèle ou de fournisseur sans toucher au
    reste du code ;
  - permettre un repli déterministe si le modèle est indisponible. La
    plateforme reste démontrable même sans IA.

Ce module ne connaît RIEN des données : il envoie du texte, reçoit du
texte. Aucun import de `observations` ni de `geography` ici — c'est la
contrainte d'architecture qui formalise l'interdiction faite au modèle
d'accéder à la base.


DEUX ÉCHECS, DEUX TRAITEMENTS

La version antérieure levait `ErreurLLM` dans les deux cas, et l'appelant
ne pouvait donc pas les distinguer :

    ErreurLLM("Modèle injoignable : Connection refused")
    ErreurLLM("JSON mal formé : Unterminated string at column 96")

Le premier est une panne : réessayer ne sert à rien, et le repli
déterministe est la bonne réponse. Le second est une génération ratée : le
modèle est là, il a mal écrit, et un second essai aboutit presque
toujours. Les confondre coûtait une réponse dégradée là où une réponse
juste était à une seconde tentative — mesuré une fois sur dix-sept
questions de préchauffage.

D'où deux exceptions, toutes deux filles d'`ErreurLLM` pour que les
appelants qui ne font pas la distinction continuent de fonctionner :

    ModeleInjoignable   -> repli déterministe
    ReponseIllisible    -> nouvelle tentative, avec un prompt différent

« Avec un prompt différent » n'est pas un détail : à température 0, le même
prompt redonne exactement la même sortie fautive. C'est à l'appelant de
changer quelque chose, et `prompt_correction` est là pour ça.
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ErreurLLM(Exception):
    """Racine commune, conservée pour les appelants qui ne distinguent pas."""


class ModeleInjoignable(ErreurLLM):
    """Le service ne répond pas. Réessayer est inutile."""


class ReponseIllisible(ErreurLLM):
    """
    Le modèle a répondu, mais sa réponse n'est pas exploitable : vide, sans
    objet JSON, ou JSON mal formé.

    Réessayer a du sens, à condition de modifier le prompt.
    """


class ClientLLM(ABC):
    @abstractmethod
    def completer(self, prompt, systeme=None, json_attendu=False,
                  max_tokens=300, temperature=0.1):
        ...

    def disponible(self):
        return True


class ClientOllama(ClientLLM):
    """
    Modèle exécuté localement. Les questions ne quittent pas
    l'infrastructure — sur des données publiques nationales, le
    traitement souverain est un critère.
    """

    def __init__(self, hote=None, modele=None, timeout=180):
        self.hote = (hote or getattr(settings, "OLLAMA_HOST",
                                     "http://localhost:11434")).rstrip("/")
        self.modele = modele or getattr(settings, "OLLAMA_MODEL",
                                        "qwen2.5:3b-instruct")
        self.timeout = timeout
        self.derniere_latence = None

    def disponible(self):
        try:
            r = requests.get(f"{self.hote}/api/tags", timeout=3)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def completer(self, prompt, systeme=None, json_attendu=False,
                  max_tokens=300, temperature=0.1):
        charge = {
            "model": self.modele,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                # Réduit la dispersion : on veut une traduction fidèle,
                # pas de la créativité.
                "top_p": 0.9,
                "repeat_penalty": 1.05,
            },
        }
        if systeme:
            charge["system"] = systeme
        if json_attendu:
            charge["format"] = "json"

        debut = time.perf_counter()
        try:
            r = requests.post(f"{self.hote}/api/generate", json=charge,
                              timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise ModeleInjoignable(f"Modèle injoignable : {e}") from e
        finally:
            self.derniere_latence = time.perf_counter() - debut

        texte = (r.json() or {}).get("response", "").strip()
        if not texte:
            # Le service a répondu : ce n'est pas une panne, c'est une
            # génération vide. Elle mérite un second essai.
            raise ReponseIllisible("Réponse vide du modèle.")
        return texte


def extraire_json(texte):
    """
    Isole un objet JSON dans une réponse, même entourée de texte ou de
    balises de code. Les petits modèles préfixent souvent leur sortie.

    Tous les échecs lèvent `ReponseIllisible` : le modèle a parlé, mal.
    """
    texte = texte.strip()
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte,
                   flags=re.MULTILINE).strip()

    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass

    debut = texte.find("{")
    if debut == -1:
        raise ReponseIllisible("Aucun objet JSON dans la réponse du modèle.")

    profondeur = 0
    for i, c in enumerate(texte[debut:], start=debut):
        if c == "{":
            profondeur += 1
        elif c == "}":
            profondeur -= 1
            if profondeur == 0:
                try:
                    return json.loads(texte[debut:i + 1])
                except json.JSONDecodeError as e:
                    raise ReponseIllisible(f"JSON mal formé : {e}") from e
    raise ReponseIllisible("Objet JSON incomplet dans la réponse du modèle.")


_client = None


def client():
    global _client
    if _client is None:
        _client = ClientOllama()
    return _client