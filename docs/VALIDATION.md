# Vérifications

## Réalisé en partie sur la première implémentation

- Appel du dispatcher normal du joueur, sans touche de fouille ni visée requise.
- Crédit de 5 unités d'argent de l'ancien monde confirmé par le joueur.
- Plusieurs transitions de cadavres contenant du butin vers un contenu nul et l'état fouillé.
- Cadavre initialement vide : état fouillable → état fouillé, en conservant la sélection native de l'action.
- Fouille automatique d'un nouveau cadavre à 4,536854 mètres ; appel mesuré à 0,4353 ms.
- Restauration des hooks, déchargement normal de QuickJS et détachement vérifiés à chaque essai terminé.

Ces résultats concernent la version Steam 1.7.1.0na, build 25361591. Ils ne mesurent pas la cadence de la nouvelle boucle résidente.

## Nouvelle boucle résidente

Qualification native : **28 scénarios réussis**, générés par `tools/autoloot_runtime.py --dummy` pendant l'installation. Le cœur C réel est exécuté dans un processus de test dédié, avec les fonctions du moteur remplacées par des stubs natifs.

| Scénario | Résultat mesuré |
| --- | --- |
| Arrivées continues de nouveaux cadavres | 10 passages, 10 recherches spatiales, 20 appels de fouille, 20 états fouillés |
| Cadence de ces passages, horloge QPC réelle | 253,54 à 280,23 ms entre débuts de passage |
| Passage normal, horloge QPC réelle | 256,59 à 281,65 ms |
| Appel spatial volontairement lent de 320 ms | 6 passages, aucun ramassage après épuisement du budget ; aucun rattrapage en rafale |
| Gardes | Rayon, identité, génération du handle, propriété du composant, contenu vide, refus et inventaire sans progression |
| Cycle de vie | Arrêts pendant recherche, fouille ou destruction ; concurrence ; changement de personnage |
| Bornes | Pagination, limite de lectures, journaux circulaires et saturation du cache de temporisation |

Tous ces scénarios vérifient la restauration du point d'entrée, la fin des workers, les registres conservés et l'équilibre allocation/destruction du vecteur. Le test de saturation des journaux utilise une horloge accélérée ; **il n'entre pas dans les chiffres de cadence réelle ci-dessus**.

La commande `--dummy` exécute également **10 tests du cycle de vie Python** : verrou d'instance, arrêt pendant le démarrage, drainage avant détachement, écriture d'état temporairement bloquée, fermeture du processus et arrêt natif signalé comme erreur. **17 tests unitaires supplémentaires** contrôlent notamment les chemins Steam, les dépendances publiées et les commandes d'installation.

Le wrapper JavaScript de production est relu séparément : les 28 scénarios natifs ne prétendent pas exécuter son branchement dans le jeu.

## Limites de validation

- La nouvelle boucle résidente à 250 ms devra être confirmée en partie : le jeu était fermé pendant sa stabilisation.
- La coopération à deux joueurs, les inventaires pleins et les transitions prolongées de session restent à exercer dans le jeu.
- Le budget de travail est contrôlé entre appels natifs ; il n'interrompt pas un appel interne du jeu lent.
- Le déclenchement dépend des ticks actifs du joueur ; il ne fournit pas une horloge indépendante du moteur.
- Les fixtures n'exercent que des processus possédés par les tests, jamais un processus de jeu.

## Contrat de mémoire native

Les blocs modifiables du module C sont alloués et conservés par JavaScript, puis fournis comme symboles externes. Cela suit le [contrat mémoire de CModule documenté par Frida](https://frida.re/docs/javascript-api/#cmodule). Leur libération attend le déchargement normal du script ; le module n'est pas détruit de force pendant un appel.
