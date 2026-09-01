# v16.0.0 — clôture interne des dix écarts SOTA

Cette version part exclusivement du commit v15.1.0 `2c1a89932b47a6f9e364b104aaae9b2a8986491e` et de son ZIP robot-certifié `0fc7180e40b8209faab51dec42f1cf83122c062bdea6310a836d653f47f94187`.

Elle ajoute dix contrôles préenregistrés : chaîne de session opaque signée, couverture exhaustive des claims, spans de preuve exacts, abstention contrôlée, contradiction et fraîcheur par claim, canonicalisation du contenu non fiable, intégrité d’évaluation aveugle, campagne de mutations, attestation de build signée SLSA-compatible et replay depuis extraction propre sans pytest.

La cohérence phénoménale reste l’invariant central et non compensable. Les nouveaux contrôles empêchent qu’un appelant substitue le texte, les identités, les reçus, l’ordre des étapes, l’autorité ou les matériaux de build autour de cet invariant.

La certification robot couvre seulement le logiciel déterministe et son attestation signée. L’indépendance organisationnelle tierce, la performance ouverte, le multi-OS réel, Sigstore/Rekor public, la validation scientifique et la licence de distribution restent `RETRY`.
