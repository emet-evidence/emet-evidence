# Addendum GRADE immobilisation après réparation de coiffe

Entrées : `data/protocols/immobilisation.json` (`outcomes_grade` O1 à O7, `subgroups`, `main_claim`, champs `certainty` et `synthesis`), `data/searches/immobilisation-2026-11-18/screening/extraction-grade-input.json` (version compacte de extraction-final.json sans les provenances, auteurs inclus ; plan, population, `protocols`, `population_detail`, `outcomes_detail`, `subgroups`, `review`, `basis` = texte réellement lu, risque de biais, `scope_decision`, `scope_note`), `screening/authors.json` (premier auteur), `screening/final.json` (flux). Les entrées dont `scope_decision` vaut « E2 » (40053065, 26510584) sont exclues : ne les utilise pas.

Question d'efficacité d'une intervention : départ « élevé » pour les essais randomisés, « élevé » pour une étude non randomisée évaluée par ROBINS-I (confusion jugée dans le risque de biais). Fonde la cotation sur les études primaires ; les revues systématiques recoupent les mêmes essais : utilise-les pour vérifier qu'aucun essai n'a été manqué, pour la cohérence et pour leurs estimations poolées (cite-les), sans les compter comme confirmations indépendantes.
- Risque de biais : essais lus sur résumé seul, absence d'aveugle de l'évaluateur de l'imagerie, perdus de vue à l'imagerie, critères rapportés par le patient sans aveugle, cohortes rétrospectives.
- Incohérence : sens et ampleur des effets entre essais.
- Caractère indirect : calendrier d'immobilisation non décrit ou contraste faible (`scope_note`), populations limitées aux petites ruptures, mobilisation active et non passive, délais de mesure.
- Imprécision : reruptures peu nombreuses, IC compatibles avec un doublement ou une division par deux du risque, effectifs ; pour la fonction, différence minimale cliniquement importante (ex. ASES environ 12 à 17 points, Constant environ 10, SST environ 2).
- Biais de publication : fiches de registre terminées sans résultats ni publication.

Critère par critère :
- O1 rerupture/cicatrisation, toutes ruptures : mobilisation précoce (passive) contre immobilisation ou mobilisation retardée.
- O2 fonction à 12 mois ou plus.
- O3 mobilité et raideur : distingue court terme (jusqu'à 3 mois) et 12 mois.
- O4 douleur.
- O5 rerupture et fonction selon la taille de la rupture : fais DEUX évaluations, O5a « ruptures petites ou moyennes » et O5b « ruptures grandes ou massives ». Indique la source des données (essais restreints à une catégorie, analyses de sous-groupe intra-essai, méta-analyses stratifiées) et la crédibilité de l'effet de sous-groupe (prédéfini ?, intra- ou inter-essais, test d'interaction). Si aucune donnée pour une catégorie, certitude « aucune donnée » et dis-le.
- O5c (ajouté, narratif) : rétraction tendineuse (stade de Patte ou mm), infiltration graisseuse, âge, technique de réparation, durée d'immobilisation : pour chacun, liste les données trouvées (étude, chiffres) ou écris « aucune étude ». Pas de cotation GRADE si aucune donnée ; sinon cote-la.
- O6 absence d'écharpe ou écharpe de confort contre immobilisation stricte.
- O7 complications et réinterventions (raideur opérée, mobilisation sous anesthésie, capsulite).

Pour chaque critère, ajoute `"n_studies"`, `"n_participants"` (somme des participants randomisés ou inclus des études primaires contributives, sans double compte d'un même essai) et `"effect_summary"` (1 à 2 phrases : sens et ampleur, avec chiffres repris de l'extraction, RR/OR poolés des revues avec IC le cas échéant).
Proposition principale : « Après une réparation de la coiffe des rotateurs, une mobilisation précoce n'augmente pas le risque de rerupture par rapport à une immobilisation. » Sa certitude est celle de O1 ; nuance dans la justification si l'effet diffère selon la taille de la rupture. Attention : « n'augmente pas » est une affirmation d'absence d'effet ; si l'IC ne permet pas d'exclure une augmentation cliniquement importante, abaisse pour imprécision et dis-le dans l'énoncé.
Références = identifiants des études (clés de extraction-final.json).
Sortie : `screening/grade-A.json` ou `screening/grade-B.json` selon ton rôle.
