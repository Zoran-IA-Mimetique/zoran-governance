# Installation — Zoran🦋 v23.1.0 expérimental

1. Pour toute installation issue d’un dépôt, exécuter d’abord `repository_head_gate.py` sur un clone Git complet de la branche cible et conserver son reçu `PASS`. Un premier échec autorise un seul re-clonage complet; un second échec interdit le livrable.
2. Vérifier le SHA-256 du ZIP reçu par un canal de confiance.
3. Extraire l’unique dossier `zoran-coherence-skill/` dans le répertoire de skills de l’hôte.
4. Installer les dépendances Python déclarées si les fonctions d’activation sont requises :

```bash
python -m pip install -r requirements-runtime.txt
```

5. Exécuter la certification locale :

```bash
python scripts/verify_release.py --full
```

Pour reproduire l’entraînement du modèle brut, installer séparément `requirements-train.txt`. Cette dépendance n’est pas requise pour l’inférence.

6. Créer un répertoire hôte persistant privé (`0700`) pour `ExecutionGovernor` et fournir le même `execution_state_root` après chaque redémarrage. Conserver un `program_id` stable de la mission scellée jusqu’à `DONE` ou `STOP`; un nouveau chat ne doit jamais en créer un autre pour contourner un budget.
7. Redémarrer ou recharger l’hôte de skills, puis vérifier que `Zoran🦋 Coherence` est découvert et que `test_execution_governor.py`, `test_repository_head_gate.py` et `test_structural_reasoning_gate.py` passent depuis la copie installée.
8. Pour l’apprentissage lexical, conserver les états et le cache Wiktionnaire dans des répertoires hôte persistants distincts; ne jamais placer de clé GMA4 dans l’état appris.
9. Ne déclarer ZMOS actif qu’après consentement utilisateur et test persistant écriture/lecture.
   Pour la coordination multi-session, sceller un seul `writer_id`; les autres sessions déposent uniquement des candidats ancrés au `BASE_HEAD` GitHub canonique avec SHA et reçus de tests.
10. Ne déclarer une mesure phénoménale disponible qu’après attestation hôte des six cadres, des sources et des quatre proxys avec valeurs et unités. La première recherche incomplète retourne `RETRY` et impose une nouvelle ressource; la seconde retourne le `VETO` de trace absente avec gyrophare et retour à l’envoyeur.
11. Ne déclarer l’affichage final autorisé qu’après vérification du certificat de session liant mission, prompt, texte exact et 18 étapes.
12. Ne déclarer la promotion robot active qu’après vérification des reçus exacts de non-conflation, claims, ressources phénoménales, cohérence phénoménale et vérité hôte, soumission du candidat, verdict `VALIDATED` et certificat signé liant ZIP, manifeste, SBOM et commit/tree source. Une preuve absente produit `WAIT_EXTERNAL` et termine le tour; elle ne relance jamais une recherche automatique.
13. Pour toute formulation issue d'un objet sémantique, fournir le même objet à `ZoranRuntime.evaluate()` et `ZoranRuntime.finalize_output()`. Le texte évalué doit être exactement la parole produite par le garde, son reçu doit être présent dans le contrôleur terminal et `speech` doit rester absent tant que la décision finale n'est pas `PASS`. Les règles Semora V5 restent des propositions en quarantaine et ne remplacent jamais ce contrôle.

`cryptography` 46.x à 50.x est requis pour Ed25519. Son absence ou l’échec de l’auto-test produit `RETRY` ou un échec de vérification, jamais un PASS implicite. `requirements-lock.txt` décrit l’environnement runtime observé par le robot ; il ne constitue pas un lock à hashes. Les droits téléphone, ChatGPT, réseau, GitHub ou MCP ne sont pas auto-acquis par l’installation.
