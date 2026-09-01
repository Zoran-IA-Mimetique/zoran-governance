# Matrice des 17 tolérances

| Dimension | Contrôle | Défaut conservateur | Exemple de blocage |
|---|---|---|---|
| métier | utilisabilité réelle dans le domaine | budgétable | écart inadmissible pour le métier |
| cohérence | compatibilité locale/générale | budgétable | contradiction avec un cadre supérieur |
| sémantique | conservation du sens | budgétable | dérive de sens au-delà du cap |
| factuelle | identité/date/chiffre/relation vraie | zéro tolérance recommandé | fait faux |
| numérique | précision/arrondi/propagation | budgétable | erreur numérique hors enveloppe |
| mesure | incertitude instrumentale/métrique | budgétable | mesure trop incertaine |
| temporelle | fraîcheur/délai/ordre temporel | budgétable | donnée périmée au-delà de la borne |
| source | provenance et traçabilité | zéro tolérance recommandé | source inexistante/perdue |
| ambiguïté | nombre/poids d'interprétations | budgétable | ambiguïté excessive |
| causale | sens et support de la causalité | zéro tolérance recommandé | A→B inversé/non supporté |
| sécurité | risque critique | zéro tolérance recommandé | seuil de sûreté dépassé |
| réglementaire | loi/norme/contrat | zéro tolérance recommandé | exigence obligatoire violée |
| ressource | temps/coût/mémoire/énergie | budgétable | budget de ressource dépassé |
| répétabilité | stabilité entre rejeux | budgétable | dérive entre exécutions |
| intégration | compatibilité entre briques | budgétable | couture hors interface |
| intentionnelle | réponse exacte au besoin | zéro tolérance recommandé | vrai mais hors sujet |
| épistémique | niveau de certitude | zéro tolérance recommandé | hypothèse présentée comme prouvée |

Les choix « zéro tolérance recommandé » sont des valeurs par défaut du skill, pas des normes universelles. Une politique métier peut les remplacer avant exécution, sauf les méta-règles de non-compensation/fail-closed/déterminisme.
