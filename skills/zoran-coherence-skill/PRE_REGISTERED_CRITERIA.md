# Multicriteria Tolerance Skill v1 — critères pré-enregistrés

Date: 2026-08-30
Scope: skill autonome de validation multicritère. Aucun couplage à Zoran.

## Familles obligatoires (17)
1. métier
2. cohérence
3. sémantique
4. factuelle
5. numérique
6. mesure
7. temporelle
8. source/provenance
9. ambiguïté
10. causale
11. sécurité
12. réglementaire/contractuelle
13. ressource
14. répétabilité
15. intégration
16. intentionnelle
17. épistémique

## Lois du moteur
- Non-compensation: aucune marge positive ne peut rembourser une violation d'une autre dimension.
- Toute charge est non négative et non remboursable: c = |delta| * poids * amplification.
- Quatre bornes simultanées: cap local, budget cumulatif de dimension, budget de cadre/métier, budget global.
- Les invariants marqués zero_tolerance sont non budgétables: toute violation => VETO.
- Toute mesure requise inconnue => RETRY, jamais PASS implicite.
- Toute amplification inconnue avec delta non nul => RETRY.
- Aucune moyenne globale ne peut convertir un VETO/FAIL/RETRY en PASS.
- Décision déterministe et reçu SHA-256 stable.
- Comptabilité exacte aux frontières décimales: pas d'epsilon caché.

## Verdicts
PASS / RETRY / VETO.

## Critères de falsification bloquants
A. 17/17 dimensions acceptent un cas propre.
B. 17/17 dimensions bloquent un dépassement local.
C. Toutes les dimensions zero_tolerance testées bloquent toute dérive non nulle.
D. Opposés +x puis -x ne s'annulent pas.
E. Une dimension ne peut pas compenser une autre.
F. Les budgets de dimension, cadre/métier et global sont chacun falsifiés indépendamment.
G. Une inconnue critique bloque.
H. Une amplification en attente de mesure bloque le drift non nul.
I. Les valeurs de frontière décimales exactes ne produisent ni faux blocage ni faux PASS.
J. Replay 10 000 fois identique sur un corpus gelé.
K. Cas transversaux: BTP, médical, finance, logiciel, texte/IA — témoin sain PASS et corruption critique bloquée.
L. Auto-application: une politique qui autorise remboursement, compensation ou PASS sur inconnue est VETO.
M. Aucun faux PASS et aucun faux blocage sur le corpus pré-enregistré.

## Promotion locale du skill
PASS_SYNTHETIC_BOUNDED_ONLY si et seulement si A-M passent.
La qualité/calibration d'une métrique fournie par un domaine réel reste hors de ce verdict et doit être déclarée RETRY si elle n'est pas établie.
