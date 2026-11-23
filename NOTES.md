Je ferais un agent orchestrateur unique ("Entreprise 360") qui route la question du commercial vers 5 outils, un par bloc. Chaque réponse suit le même format : le chiffre clé, le signal (écart vs benchmark ou vs N-1), puis une action proposée. Ça colle à la contrainte du hackathon : l'IA ne se contente pas de reformuler des données, elle déclenche des actions.

Un outil par bloc, avec des questions types :

Absentéisme : « Comment évolue l'absentéisme chez ce client ? », « Quels établissements ou tranches d'âge sont les plus touchés ? » (la flèche rouge de ton paperboard : interroger les inputs en langage naturel).
Services actionnables : « Quels services proposer à ce client ? », « Qu'a donné Previa chez eux ? ». La réponse recommande le service (Previa, contrôle médical, prévention) selon le niveau d'absentéisme, avec les résultats obtenus ailleurs.
Benchmark : « Où se situe ce client vs son secteur et sa région ? ». Chaque indicateur sort avec un écart (au-dessus, dans la moyenne, en dessous).
Garanties non utilisées : « Quelles garanties sont sous-utilisées ? » (Itelis, téléconsultation, 2e avis, assistance). La réponse propose un angle de discussion pour le RDV client.
Bilan gestion : « Comment se passe la gestion de ce client ? » (délais de traitement, taux de réclamation et dossiers concernés, consommations de santé, satisfaction vs moyenne du secteur).

Points de conception :

Contexte client : le commercial sélectionne ou nomme l'entreprise une fois, et tous les outils en héritent. Le contrôle d'accès (périmètre portefeuille du commercial) se fait dans les outils, pas dans le prompt.
Question large (« Fais-moi le point sur X ») : l'agent appelle les 5 outils en parallèle et remonte les 2 ou 3 signaux les plus saillants, pas les 5 blocs en entier.
Chaînage naturel : un absentéisme élevé (1) déclenche la suggestion Previa ou contrôle médical (2). Une garantie sous-utilisée (4) devient une opportunité commerciale.
Réponses ancrées dans des requêtes BigQuery validées par bloc (outils MCP ou skills), pour éviter le text-to-SQL libre sur des données sensibles et garder la traçabilité.

Tu veux que je détaille la définition des 5 outils (entrées, sorties, tables DSN et prestations utilisées) ou que je rédige le prompt système de l'orchestrateur ?
