# Calcul exact et profil chimie

## Chemin obligatoire

Pour un calcul reconnu, suivre ce chemin avant toute comparaison statistique :

1. repérer l'opération demandée ;
2. lier chaque nombre à l'objet nommé dans la question ;
3. vérifier que les unités sont compatibles ;
4. calculer avec des fractions exactes, jamais avec `eval` ;
5. vérifier le résultat par l'opération inverse ;
6. comparer la réponse proposée au résultat exact.

Une liaison complète et un résultat identique donnent `PASS`. Une liaison
complète et un résultat différent donnent `VETO`. Une opération reconnue avec
un nombre, une unité ou un objet manquant donne `RETRY` : l'absence de preuve
n'est pas une hallucination démontrée.

Le noyau fermé couvre les différences, sommes, moyennes, produits, quotients,
variations en pourcentage, fractions, conversions simples d'unités et équations
linéaires à une inconnue. Une expression non linéaire ou une famille inconnue
reste hors portée au lieu d'être approximée.

## Profil chimie

Le profil chimie se place au-dessus du noyau de calcul et garde trois niveaux :

- `ORDINARY` : formule, masse molaire et équilibrage symbolique ; résultat
  direct, sans avertissement automatique ;
- `SENSITIVE` : température, pression, concentration, quantité ou changement
  d'échelle ; exiger toutes les valeurs et unités, puis afficher un avertissement
  ciblé sur les conditions réelles ;
- `DANGEROUS` : demande procédurale concernant explosifs, armes chimiques,
  agents neurotoxiques ou gaz toxiques ; ne produire aucune procédure
  exploitable, proposer seulement prévention, sécurisation ou professionnel.

Un mot dangereux cité dans une question documentaire ne suffit pas à classer
la demande comme procédure. Le profil exige à la fois un sujet dangereux et
une intention d'action. Cette distinction évite les avertissements bruyants et
les blocages par simple mot-clé.

Les masses molaires utilisent des poids atomiques conventionnels intégrés et
ne valent pas certificat de métrologie. L'équilibrage couvre les équations
neutres à solution unique dans le périmètre d'éléments déclaré. Les charges,
isotopes, hydrates complexes, cinétiques, équilibres, protocoles de laboratoire
et molécules structurelles avancées restent hors portée.

## Dette et dépendances

Le chemin runtime utilise uniquement la bibliothèque standard Python. Il
n'ajoute donc aucune dépendance scientifique opaque au cœur du skill. SymPy,
Pint, ChemPy ou RDKit pourront être ajoutés plus tard comme adaptateurs
optionnels, seulement avec tests d'équivalence, verrouillage de versions et
échec fermé lorsque l'adaptateur manque.
