# Ancrage chantier obligatoire — HEAD gate

Avant toute lecture, analyse, modification ou production fondée sur un dépôt Git :

1. effectuer un clone Git complet ; un clone shallow, partiel, promisor, une reconstruction de fichiers ou des téléchargements unitaires sont interdits ;
2. checkout de la branche cible exacte ;
3. afficher `git rev-parse HEAD` ;
4. lire la tête distante de `refs/heads/<branche>` avec `git ls-remote --heads` ;
5. exiger l’égalité octet pour octet des deux SHA et conserver le reçu du gate.

`repository_head_gate.py` vérifie aussi l’intégrité des objets Git avec
`git fsck --full --no-dangling`, neutralise les replace objects et refuse un
remote local ou fabriqué par l’appelant.

Un premier échec produit `RETRY` et autorise une seule action : refaire un clone
complet depuis le remote réseau, checkout de la même branche cible et rejouer le
gate avec `--after-full-reclone`. Tout nouvel échec produit `VETO`.

Aucune lecture de contenu, correction, test, commit, ZIP, certification,
installation ou promotion ne peut compenser l’absence de ce `PASS`. Tout
livrable produit sans ancrage HEAD vérifié est invalide, quel que soit son
contenu. Le gouverneur d’exécution persiste l’usage de l’unique tentative ;
changer de session, de chemin local ou de programme ne la remet pas à zéro.

```bash
python3 /chemin/du/skill/repository_head_gate.py /chemin/du/depot branche-cible
```

Après l’unique re-clonage :

```bash
python3 /chemin/du/skill/repository_head_gate.py /nouveau/clone branche-cible --after-full-reclone
```
