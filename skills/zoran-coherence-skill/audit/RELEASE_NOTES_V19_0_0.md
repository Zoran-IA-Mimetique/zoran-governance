# Zoran🦋 Coherence Skill v19.0.0

## Changement central

Le candidat possède désormais son chemin brut `contexte + question + réponse → décision`. Il ne dépend plus d’un appelant pour fabriquer les propositions qui servent à évaluer une réponse. Le gate sélectionne le cadre QA, dialogue ou résumé, calcule 39 mesures bornées, applique un modèle logistique multicadre scellé, cite les phrases de preuve et émet exactement deux reformulations lorsque la marge de décision indique un doute.

Le reçu du gate est lié au reçu global du runtime et injecté comme contrôle terminal candidat. Une recombinaison numérique locale ou une omission de portée oui/non sur « les deux » est non compensatoire.

## Gouverneur anti-boucle

Le candidat ajoute `execution_governor.py`. La décision sémantique
`PASS/RETRY/VETO` est désormais indépendante de l’état du scheduler
`DONE/CONTINUE/WAIT_EXTERNAL/STOP`. Un journal privé `0600`, append-only et
hash-chaîné cumule le budget par identifiant de programme stable entre chats et
processus. Il ferme les resets de session, les répétitions état/action, deux
absences consécutives de delta matériel, les plafonds de cycles/temps/outils et
les journaux altérés. Une dépendance utilisateur, connecteur ou externe absente
devient un `WAIT_EXTERNAL` terminal sans polling. La construction et le
checkpoint du candidat restent distincts de la promotion signée.

## Entraînement et frontière

- HaluEval uniquement : 48 000 cas d’entraînement, 12 000 cas de validation groupée par contexte/question.
- Aucune étiquette HaluBench utilisée pour l’entraînement ou les seuils.
- Validation du modèle multicadre : 86,55 % d’exactitude, 90,38 % d’acceptation fidèle et 82,72 % de rappel de blocage des hallucinations.
- QA de validation : 99,70 % d’exactitude, 100 % d’acceptation fidèle, 99,41 % de rappel de blocage.
- Ces mesures ne sont pas une certification SOTA et la validation a servi au choix des seuils.

## Falsification enregistrée

La campagne v19 rejoue 4 000 cas : vérité locale, recombinaison numérique, omission de portée et opposition de matière. Le succès attendu est 4 000/4 000 avec zéro faux PASS et zéro faux blocage. La campagne anti-boucle rejoue 1 200 cas sur douze familles : resets intersessions, attentes externes, absence de polling, budgets, répétitions, stagnation, séparation build/promotion, décisions terminales et altération du journal. Le benchmark public HaluBench reste un holdout séparé et doit être rapporté distinctement.

## Rollback

Le ZIP v18 et son commit `bb840af06b4c80c82e474c698f5e1e64f68a0f18` restent les références de rollback.
