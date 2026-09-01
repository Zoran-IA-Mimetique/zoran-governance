# Zoran🦋 Coherence Skill v21.0.0

## Résultat

La v21 ferme les confusions de relation qui survivaient au recouvrement lexical : matière/opposition, sujet-source, direction, rôle, chronologie, période, unité, rang, causalité locale, quantificateur, acronymes et groupes taxonomiques. Le moteur produit des preuves structurelles déterministes avant le classifieur brut.

Sur le diagnostic public épinglé de 4 900 cas hors HaluEval, le rappel de blocage passe de 93,9815 % à 99,4444 % et l’acceptation fidèle de 24,2336 % à 31,5693 %. Les faux PASS passent de 130 à 12 et les faux blocages de 2 076 à 1 875. Ce corpus a été inspecté pendant le développement : ce résultat est un diagnostic révélé, pas un holdout frais, un benchmark SOTA comparable, ni une preuve d’universalité.

Les tranches `covidQA`, `pubmedQA` et la tranche portant le libellé amont `RAGTruth` atteignent zéro faux PASS dans ce replay. Le libellé `RAGTruth` est uniquement le nom exact du sous-corpus public; Zoran utilise exclusivement ZMOS comme couche mémoire et trace.

## ZMOS Writer unique

ZMOS reçoit la file de coordination : missions, états, verrous, candidats `BASE_HEAD`/SHA et reçus. Les aides peuvent uniquement déposer des candidats. Un Writer scellé unique possède l’intégration, le push et la synchronisation du SHA GitHub final. GitHub reste canonique et ZMOS ne devient jamais une source de vérité ou une autorité de promotion.

## Limite principale

L’acceptation fidèle publique reste faible, surtout sur `pubmedQA` et le sous-corpus externe multi-passages. Les 12 faux PASS bruts restants sont conservés dans un registre de contestations sans ajuster le score. La v21 privilégie la fermeture des affirmations non prouvées; une prochaine évaluation doit utiliser un nouveau holdout gelé et indépendant pour mesurer la généralisation sans réutiliser les erreurs révélées ici.
