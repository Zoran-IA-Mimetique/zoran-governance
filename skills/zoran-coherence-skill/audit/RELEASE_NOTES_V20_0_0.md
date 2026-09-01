# Zoran🦋 Coherence Skill v20.0.0

## Changement central

La v20 ajoute un moteur de preuves structurelles déterministe en amont du modèle multicadre. Il couvre les sommes, cellules et unités financières, comptes explicites, compléments de pourcentage, polarités oui/non, comparaisons numériques et réponses multi-affirmations. Son entrée est limitée à `context`, `question` et `answer`; ZMOS reste l’unique couche de mémoire et de résolution de traces.

## Ancrage chantier Git

`repository_head_gate.py` rend non compensatoire la preuve d’ancrage demandée : clone complet non superficiel et non partiel, branche cible exacte, objets Git intègres, distant réseau et égalité exacte entre `git rev-parse HEAD` et la tête distante. Le premier échec produit `RETRY` avec un seul re-clonage complet restant; le second produit `VETO`. Un livrable sans reçu `PASS` est invalide.

## Falsification enregistrée

La campagne v20 contient 16 familles équilibrées, chacune composée d’un contrôle fidèle et de sa falsification : cellules/années financières, unités, sommes, comptes, compléments de pourcentage, polarité oui/non, comparaisons et multi-affirmations. Le critère de succès est zéro faux PASS et zéro faux blocage sur le générateur déterministe gelé.

Cette campagne vérifie les invariants implémentés; elle ne constitue pas un benchmark public ouvert ni une certification tierce.

## Rollback

Le ZIP v19 SHA-256 `1e7dac55d24712bdb1bc65e07c0f3f3941b2e0840c837d5f0cf20e796d492e72` et le commit `19958f72638901fea0f89eb9a662d840c970a265` restent les références de rollback.
