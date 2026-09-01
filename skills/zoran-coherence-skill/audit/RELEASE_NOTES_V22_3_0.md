# Zoran🦋 Coherence Skill v22.3.0 — candidat expérimental

Cette version n'est ni promue ni certifiée. Elle superpose trois contrôles au
moteur v21 : cadres colorés à motifs, calcul exact et profil chimie borné.

Le calcul exact lie chaque opérande à l'objet nommé dans la question, contrôle
les unités, calcule avec des fractions et vérifie le résultat par l'opération
inverse. Le cas « ménages de plus que familles » est désormais une différence
nommée ; un résultat faux est contredit et des opérandes ambigus produisent
`RETRY` au lieu d'être étiquetés comme hallucination.

Le profil chimie couvre les masses molaires et l'équilibrage de réactions
neutres. Il distingue calcul courant, données sensibles incomplètes et demande
procédurale dangereuse. Les avertissements sont ciblés ; aucun avertissement
générique n'est ajouté aux calculs courants.

Le runtime scientifique n'ajoute aucune dépendance externe. SymPy, Pint,
ChemPy et RDKit restent des adaptateurs ultérieurs possibles, soumis à des
tests d'équivalence, à un verrouillage de versions et au même échec fermé.

Le benchmark public n'est pas relancé par cette construction. La condition de
passage reste la non-régression interne complète, suivie d'une décision séparée
sur la capacité réelle à améliorer le résultat public.
