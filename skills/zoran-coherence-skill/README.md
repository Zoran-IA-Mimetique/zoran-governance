# Zoran🦋 Coherence Skill v21.0.0

Statut source : **candidat expérimental v21**. Cette édition étend le moteur structurel aux relations factuelles locales, chronologies, rôles, directions, périodes, comparaisons et compositions multi-passages. Elle ajoute aussi la coordination ZMOS à Writer unique. Ce statut ne constitue ni une certification tierce ni une preuve d’absence universelle d’hallucinations.

Le HEAD gate exige un clone complet, non superficiel et non partiel, le checkout de la branche cible, l’intégrité des objets Git et l’égalité exacte entre `git rev-parse HEAD` et le SHA distant. Son premier échec autorise un seul re-clonage complet; le second produit `VETO`. Aucun score ni contenu ne compense son absence.

Le moteur structurel traite directement les sommes, cellules et unités financières, comptes explicites, compléments de pourcentage, polarités oui/non, comparaisons, chronologies, rôles, directions, événements classés, relations factuelles locales et réponses multi-affirmations. Son contrat d’entrée reste strictement `contexte + question + réponse`; ZMOS est l’unique couche de mémoire et de résolution de traces du système.

ZMOS peut recevoir les missions, états, verrous, candidats `BASE_HEAD`/SHA et reçus des sessions auxiliaires. Un seul Writer peut intégrer, pousser et synchroniser le SHA GitHub final. GitHub reste canonique; ZMOS n’est ni un dépôt de vérité ni une autorité de promotion.

Le modèle multicadre est entraîné exclusivement sur HaluEval avec séparation groupée contexte/question : 48 000 cas d’entraînement et 12 000 cas de validation. Aucune étiquette HaluBench n’entre dans l’entraînement ou le choix des seuils statistiques. Les règles v21 ont toutefois été développées après inspection des erreurs du diagnostic public épinglé; ce corpus n’est donc plus un holdout frais et ses résultats restent diagnostiques. L’inférence n’exige que la bibliothèque standard; `scikit-learn` est cantonné à la reproduction de l’entraînement.

Au premier doute ou à la première incohérence multicadre, Zoran🦋 produit deux reformulations sémantiquement équivalentes avant toute recherche externe. Si elles ne conservent pas exactement acteurs, relations, objets, nombres, dates, négations et modalité, la recherche ne démarre pas. Les faits portant sur une personne publique sont ensuite vérifiés sur Internet et liés proposition par proposition à une preuve locale.

Cette édition conserve la cohérence phénoménale comme invariant central et ferme les sept faux PASS reproduits sur v16 : fait relabellisé, source inventée, citation hors sujet, abstention qui affirme encore, omission sémantique, injection paraphrasée et mesure phénoménale auto-écrite. Elle ajoute un premier passage Wikimedia signé, l’entailment claim-citation, un round trip sémantique exact, deux tours de recherche phénoménale au maximum, l’attestation hôte des cadres/sources/proxys/valeurs et une chaîne de session Ed25519 à 18 étapes.

Le gouverneur sépare désormais la décision d’évaluation `PASS/RETRY/VETO` de l’état d’exécution `DONE/CONTINUE/WAIT_EXTERNAL/STOP`. Son journal hash-chaîné est indexé par un identifiant de programme stable, pas par le chat. Il cumule cycles, temps, appels d’outils et stagnation entre processus, interdit la répétition d’un même couple état/action et transforme une capacité externe absente en attente terminale sans polling. La phase `BUILD` peut être checkpointée sans signature de promotion; la phase `PROMOTION` ne le peut pas.

## Vérification

```bash
python scripts/verify_release.py --full
```

Le vérificateur reconstruit deux ZIP identiques, réalise deux extractions sûres, vérifie Ed25519 et les dépendances observées, exécute la suite via le runner source embarqué et rejoue les campagnes déterministes, dont la campagne ZMOS structurelle. Pytest n’est pas requis.

## Construction reproductible

```bash
python scripts/build_release.py --write-manifest --output dist/ZORAN_COHERENCE_SKILL_v21.0.0_CANDIDATE.zip
```

Deux constructions consécutives sur les mêmes octets source doivent produire le même SHA-256.

## Entrées principales

- `SKILL.md` et `references/` : contrat agent progressif ;
- `repository_head_gate.py` : ancrage clone complet, branche cible et HEAD distant exact ;
- `structural_reasoning_gate.py` : preuves structurelles déterministes avant classification ;
- `zmos_writer_coordination.py` : file ZMOS ancrée au HEAD canonique et actions d’intégration/push réservées au Writer ;
- `zoran_runtime.py` : orchestration ;
- `execution_governor.py` : budget global persistant, préflight des capacités et états terminaux d’exécution ;
- `raw_text_coherence_gate.py` et `raw_text_coherence_model.json` : analyse brute multicadre et modèle scellé ;
- `phenomenal_coherence.py` : trajectoire six cadres et bénéfice causal obligatoires ;
- `phenomenal_resource_gate.py` : deux recherches maximum et aucune mesure partielle ;
- `phenomenal_resource_attestation.py` : attestation hôte des cadres, sources, proxys, valeurs et unités ;
- `semantic_non_conflation.py` : séparation obligatoire des concepts et identité exacte des actions ;
- `question_reformulation_gate.py` : deux reformulations convergentes avant recherche en cas de doute ;
- `proposition_coherence_gate.py` : contrat de question et liaison sujet–relation–objet à la preuve locale ;
- `claim_evidence_gate.py` et `wikimedia_evidence.py` : cohérence intrinsèque, premier passage Wikimedia signé, spans exacts, entailment, contradictions, fraîcheur et abstention ;
- `batch_learning_runtime.py` et `components/` : apprentissage lexical en quarantaine, réutilisation à froid, correction du contrat GMA4 et cache Wiktionnaire ;
- `contrastive_corpus_gate.py` : gel des paires fidèle/hallucinée et séparation stricte train/validation/holdout ;
- `host_truth_guard.py` : attestation signée des contrôles de vérité liés à la sortie exacte ;
- `host_session_guard.py` : vérification de la chaîne de session signée et du texte exact affiché ;
- `blind_eval.py` : intégrité du split public, de l’oracle caché et des traces ;
- `robot_handoff_guard.py` : découverte, soumission, verdict et confiance du robot ;
- `tolerance_skill.py` et `sensor_layer.py` : contrôle 17 familles ;
- `terminal_controller.py` : autorité de clôture ;
- `delivery_reviewer.py` : revue liée à l’objectif ;
- `zmos_memory.py` et `zmos_coherence_selector.py` : mémoire intègre et rappel contradictoire ;
- `bounded_truth_engine.py` et `source_coherence.py` : preuve bornée et racines de provenance ;
- `scripts/test_runner.py` et `scripts/verify_release.py` : replay source sans pytest et vérification déterministe.

La loi fermée `PASS` / `RETRY` / `VETO`, le budget de deux recherches et l’interdiction des résultats numériques sans trace signée sont définis dans `references/decision-semantics.md`. Les limites de portée sont explicitées dans `references/security-limitations.md` et `references/evaluation-and-release.md`.
