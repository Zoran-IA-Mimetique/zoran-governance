# Parole sémantique et recompréhension

La parole publique part d'un objet sémantique structuré. Elle n'est libérée que
si un second parseur reconstruit exactement le même objet et si le normaliseur
d'équivalence retrouve les mêmes acteurs, relations, objets, négations,
modalités, conditions, ordres, références et unités.

La chaîne est :

`objet sémantique → parole → recompréhension → équivalence → libération`

- `PASS` libère la parole exacte.
- `RETRY` retient une formulation qui n'a pas encore retrouvé le même objet.
- `VETO` bloque une entrée invalide, une contradiction ou une reconstruction
  impossible.

Les changements de cadre et de polarité sont résolus avec une portée explicite.
Un mot voisin ne suffit pas : par exemple, `pas` n'est une négation que si le
signal `ne/n'` est présent dans la même proposition bornée.

Semora V5 peut apprendre des règles de réparation générales sur un corpus gelé.
Ces règles restent en quarantaine et ne peuvent ni prononcer une réponse à elles
seules, ni valider, ni promouvoir un candidat. Le professeur externe propose ;
les portes déterministes décident.

Source importée en lecture seule :
`zorania2025/Zoran-IA-deteriniste`, branche
`exp/semantic-color-pattern-v0`, révision
`7b00352914aaacd429f550ce4224d2b3133dea7d`.
