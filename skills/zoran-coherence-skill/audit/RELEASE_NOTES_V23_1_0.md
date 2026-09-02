# Zoran🦋 Coherence Skill v23.1.0 — candidat expérimental

## Objet

Réduire la taille et le rayon de changement des deux noyaux centraux sans ajouter de règle ni modifier une décision.

## Changements

- `structural_reasoning_gate.py` passe de 2 779 à 1 349 lignes et devient une façade.
- Les primitives partagées, les règles numériques et les règles factuelles sont séparées dans trois modules sans cycle d'import.
- `zoran_runtime.py` passe de 351 à 217 lignes.
- L'évaluation de l'orchestrateur est séparée en trois étapes ; la plus complexe passe de 68 à 23 branches.
- Aucune dépendance d'exécution n'est ajoutée.

## Équivalence observée avant le changement de version

- 859 tests et 56 sous-tests passent avant et après.
- 742 contrôles du runner source passent.
- Sept parcours complets de l'orchestrateur produisent exactement les mêmes octets.
- Les campagnes déterministes v19 et v20 produisent exactement les mêmes octets.

Ces contrôles démontrent l'équivalence sur les chemins couverts. Ils ne constituent ni une preuve universelle d'absence de régression, ni une certification externe.
