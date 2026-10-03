import { useEffect, useRef, useState } from "react";

import Catalogue from "./components/Catalogue";
import Clarification from "./components/Clarification";
import PlanRequete from "./components/PlanRequete";
import Question from "./components/Question";
import Refus from "./components/Refus";
import Resultat from "./components/Resultat";
import { getHistorique, poser } from "./lib/api";

/**
 * StatSense AI — interface.
 *
 * L'écran suit l'architecture : la question, puis le plan de requête
 * qu'en a tiré le modèle, puis le résultat calculé. Cette séquence
 * visible est l'argument du projet — l'intelligence artificielle traduit,
 * le moteur déterministe calcule.
 */

const SECOURS = [
  "Quelles sont les 5 régions les plus peuplées ?",
  "Montre-moi l'accès à l'électricité sur une carte",
  "Comment le chômage a-t-il évolué au Sénégal ?",
  "Où les ménages sont-ils les plus grands ?",
  "Quel est le PIB de Thiès ?",
];

export default function App() {
  const [onglet, setOnglet] = useState("poser");
  const [question, setQuestion] = useState("");
  const [posee, setPosee] = useState("");
  const [reponse, setReponse] = useState(null);
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState(null);
  const [suggestions, setSuggestions] = useState(SECOURS);
  const zoneReponse = useRef(null);

  useEffect(() => {
    getHistorique()
      .then((h) => {
        if (h.suggestions?.length) setSuggestions(h.suggestions.slice(0, 5));
      })
      .catch(() => {});
  }, []);

  const interroger = async (q) => {
    setOccupe(true);
    setErreur(null);
    setReponse(null);
    setPosee(q);
    setQuestion(q);
    try {
      const r = await poser(q);
      setReponse(r);
      requestAnimationFrame(() =>
        zoneReponse.current?.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        }),
      );
    } catch (e) {
      setErreur(e.message);
    } finally {
      setOccupe(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-filet">
        <div className="max-w-5xl mx-auto px-5 sm:px-8 py-4 flex items-baseline justify-between gap-6 flex-wrap">
          <div className="flex items-baseline gap-3">
            <span className="font-chiffre text-xl">StatSense AI</span>
            <span className="text-sm text-sourdine hidden sm:inline">
              Statistiques publiques du Sénégal
            </span>
          </div>

          <nav className="flex gap-5 text-sm">
            {[
              ["poser", "Interroger"],
              ["catalogue", "Données disponibles"],
            ].map(([cle, libelle]) => (
              <button
                key={cle}
                type="button"
                onClick={() => setOnglet(cle)}
                className={`pb-0.5 border-b-2 transition-colors ${
                  onglet === cle
                    ? "border-echelle-4 text-encre"
                    : "border-transparent text-sourdine hover:text-encre"
                }`}
              >
                {libelle}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto px-5 sm:px-8 py-8 sm:py-12">
        {onglet === "catalogue" ? (
          <>
            <h2 className="font-chiffre text-2xl mb-1">
              Données disponibles
            </h2>
            <p className="text-sourdine text-sm mb-8 max-w-lecture">
              Tout ce que la plateforme exploite, avec sa granularité, sa
              période couverte et sa provenance.
            </p>
            <Catalogue />
          </>
        ) : (
          <>
            {!reponse && !occupe && (
              <div className="mb-8 max-w-lecture">
                <h1 className="font-chiffre text-3xl sm:text-4xl leading-tight">
                  Posez votre question en français.
                  <br />
                  Obtenez un chiffre exact, sourcé.
                </h1>
                <p className="mt-4 text-sourdine leading-relaxed">
                  Le modèle traduit votre question en requête ; le calcul
                  est fait par un moteur déterministe sur les données de
                  l'ANSD. Aucun chiffre n'est produit par l'intelligence
                  artificielle.
                </p>
              </div>
            )}

            <Question
              valeur={question}
              onChange={setQuestion}
              onEnvoyer={interroger}
              occupe={occupe}
            />

            {!reponse && !occupe && (
              <div className="mt-5">
                <div className="text-sm text-sourdine mb-2">
                  Par exemple
                </div>
                <div className="flex flex-wrap gap-2">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => interroger(s)}
                      className="text-sm border border-filet rounded px-3 py-1.5
                                 hover:border-echelle-3 hover:bg-echelle-1/50
                                 transition-colors text-left"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div ref={zoneReponse} className="mt-8 space-y-5">
              {occupe && (
                <div className="bloc p-6">
                  <div className="h-3 w-40 bg-echelle-1 rounded animate-pulse" />
                  <div className="mt-4 h-24 bg-echelle-1/60 rounded animate-pulse" />
                </div>
              )}

              {erreur && (
                <div className="bloc border-signal/30 bg-signalclair p-6">
                  <p>{erreur}</p>
                  <p className="text-sm text-sourdine mt-2">
                    Vérifiez que le serveur est démarré, puis réessayez.
                  </p>
                </div>
              )}

              {reponse && (
                <>
                  <PlanRequete plan={reponse.plan} meta={reponse.meta} />

                  {reponse.statut === "ok" && (
                    <Resultat
                      resultat={reponse.resultat}
                      texte={reponse.texte}
                    />
                  )}

                  {reponse.statut === "refus" && (
                    <Refus reponse={reponse} onSuggestion={setQuestion} />
                  )}

                  {reponse.statut === "clarification" && (
                    <Clarification
                      reponse={reponse}
                      onChoix={(libelle) =>
                        setQuestion(`${posee} — ${libelle}`)
                      }
                    />
                  )}
                </>
              )}
            </div>
          </>
        )}
      </main>

      <footer className="border-t border-filet">
        <div className="max-w-5xl mx-auto px-5 sm:px-8 py-4 text-xs text-sourdine">
          Données de l'Agence nationale de la Statistique et de la
          Démographie. Modèle de langage exécuté localement — les
          questions ne quittent pas l'infrastructure.
        </div>
      </footer>
    </div>
  );
}
