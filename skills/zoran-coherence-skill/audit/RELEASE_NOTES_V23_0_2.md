# Zoran🦋 Coherence Skill v23.0.2 — candidat expérimental

## Correction issue de l'audit 360°

Un tirage massif a révélé qu'un nombre ressemblant à une année dans le nom
d'une personne pouvait satisfaire à tort la couverture numérique d'une réponse
sur sa date de naissance. La preuve structurelle lie désormais le nom exact au
prédicat `was born in`, puis compare uniquement l'année portée par ce prédicat.
Une liaison ambiguë ou une réponse sans date isolable reste non résolue au lieu
d'être validée. Une preuve factuelle non résolue est désormais bloquante et ne
peut plus être compensée par le score statistique global.
Un nombre intégré au nom de la personne n'est plus interprété comme la période
demandée lorsque la question porte précisément sur sa naissance.
Un sujet vide après normalisation est non résolu et bloqué au lieu d'être lié à
une phrase quelconque du contexte.

## Mesures internes

- campagne fautive avant correction : 19 980 décisions correctes sur 20 000,
  avec 20 faux passages ;
- même campagne après correction : 20 000 décisions correctes sur 20 000,
  sans faux passage ni faux blocage ;
- campagne ciblée de noms numériques, dates voisines et contextes ambigus :
  100 000 décisions conformes sur 100 000 ;
- suite complète : 859 tests et 56 sous-tests réussis ;
- vérificateur autonome : 742 contrôles réussis sans dépendre de pytest ;
- paquet reproductible et campagnes lourdes : voir les reçus du rapport d'audit
  rattaché à cette version.

Ces résultats portent sur les cas enregistrés et générés par le harnais local.
Ils ne prouvent ni une absence universelle d'hallucinations, ni une supériorité
ouverte, ni une certification scientifique indépendante. La promotion reste
interdite sans les reçus externes exigés.
