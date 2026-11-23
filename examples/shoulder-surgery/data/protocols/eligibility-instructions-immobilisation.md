# Consignes d'éligibilité (page « Faut-il immobiliser l'épaule après une réparation de la coiffe des rotateurs ? »)

Tu es un relecteur indépendant. Lis `data/protocols/immobilisation.json` (PICO, sous-groupes, inclusion, codes E1–E8, `scope_decisions`) et `data/protocols/screening-instructions-immobilisation.md`. Ne lis rien d'autre du dépôt que ces deux fichiers et les fichiers de ton lot dans `data/searches/immobilisation-2026-11-18/screening/eligibility/` : ni le travail d'un autre relecteur, ni les pages HTML, ni `data/question-*.json`. Pas de réseau.

Chaque fichier contient : ID, titre, ACCÈS (texte intégral, résumé, titre seulement, fiche du registre), résumé, extrait des méthodes, texte intégral s'il est ouvert. Lis le résumé et, si le texte intégral est présent, les méthodes (protocole postopératoire de chaque groupe) et résultats assez pour décider.

**Inclure** :
- un essai randomisé ou une étude comparative non randomisée chez des adultes opérés d'une réparation de coiffe, dont les groupes diffèrent par le calendrier d'immobilisation ou de mobilisation : mobilisation passive (ou active) précoce contre immobilisation stricte ou mobilisation retardée ; absence d'écharpe ou écharpe de confort contre immobilisation ; durées d'immobilisation différentes ; rééducation « accélérée » contre « conservatrice » si le début de la mobilisation ou la durée d'immobilisation diffère (préciser dans `reason` les calendriers des deux groupes) ; rapportant cicatrisation/rerupture, fonction, mobilité, raideur, douleur ou complications ;
- une étude de cohorte comparant des patients selon le délai de début de la rééducation (base de données) si le délai diffère entre groupes ;
- un essai enregistré (fiche du registre) répondant à ce PICO, publié ou non : `decision` include, `outcomes` ["registre"] ;
- une revue systématique ou méta-analyse sur la mobilisation précoce contre retardée ou l'immobilisation après réparation de coiffe (y compris revue de méta-analyses, méta-analyse en réseau de protocoles postopératoires), rapportant des résultats.

Exclure avec le code du protocole sinon. Même calendrier d'immobilisation et de mobilisation dans les deux groupes (type d'attelle à durée égale, coussin d'abduction contre écharpe, hydrothérapie contre rééducation à terre, supervisée contre domicile, arthromoteur contre manuel à date égale), ou début du seul renforcement/de la seule mobilisation active alors que la mobilisation passive et l'immobilisation sont identiques = E2 (le préciser). Analyse de facteurs de rerupture sans comparaison de calendrier = E2. Série sans groupe témoin = E3. Revue narrative, commentaire, lettre, erratum, protocole d'essai sans résultats, analyse de fragilité statistique, recommandation non systématique = E4. Doublon, prépublication ou résumé de congrès d'un article présent, thèse reprenant un essai publié, fiche de registre d'un essai publié présent = E5 (cite l'id conservé dans `reason`).

`not_retrieved` : seulement si ni résumé ni texte ne permettent de décider (ACCÈS « titre seulement » sans information suffisante).

## Sortie
Un JSON couvrant tous les fichiers de ton lot (clé = valeur de la ligne « ID: ») :
```json
{"12345678": {"decision": "include", "code": null, "basis": "texte intégral", "design": "ECR", "comparison": "mobilisation passive J1 contre écharpe stricte 4 semaines", "tear_size": "petite à moyenne", "outcomes": ["O1","O2","O3"], "reason": "…"},
 "23456789": {"decision": "exclude", "code": "E2", "basis": "résumé", "reason": "…"}}
```
`basis` = ce qui a réellement été lu (texte intégral, résumé, titre, fiche du registre). `outcomes` selon les critères O1–O7 du protocole. Vérifie par script que toutes les clés sont présentes et que chaque exclusion a un code. Réponds en une ligne : inclusions, exclusions, non récupérées.
