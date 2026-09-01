# Zoran🦋 Coherence Skill v23.0.0 — candidat expérimental

## Objet

Cette version importe dans le skill le noyau de formulation sémantique de la branche Zoran `exp/semantic-color-pattern-v0`, ancrée au commit exact `7b00352914aaacd429f550ce4224d2b3133dea7d`.

Le sens de transfert est exclusivement **Zoran → skill**. Aucun fichier du dépôt Zoran n'est modifié par ce lot.

## Ajouts

- formulation naturelle à partir d'un objet sémantique structuré ;
- recompréhension de la phrase produite ;
- comparaison exacte V4 des acteurs, relations, objets, polarités, modalités, conditions, ordre, références et unités ;
- libération de la parole uniquement sur `PASS` ;
- blocage déterministe sur donnée manquante, contradiction ou perte de sens ;
- distinction entre négation réelle et article dans une expression telle que « un pas » ;
- règles Semora V5 conservées en quarantaine, sans autorité de validation ni de promotion ;
- corpus et reçus aveugles figés importés avec leurs empreintes d'origine.

## Mesures internes

- base avant intégration : 749 tests réussis et 56 sous-tests réussis ;
- candidat après intégration : 845 tests réussis et 56 sous-tests réussis ;
- delta : 96 tests réussis supplémentaires, sans régression observée.

Ces mesures sont des contrôles internes. Elles ne constituent ni un benchmark externe frais, ni une certification indépendante, ni une preuve universelle contre les hallucinations.

## Statut

Le lot est constructible et testable comme candidat expérimental. La promotion reste interdite tant que les autorités externes et reçus requis par le skill n'ont pas validé l'artefact exact.
