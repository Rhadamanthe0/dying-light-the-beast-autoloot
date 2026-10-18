# Vérifications

## Réglage actuel : 2 mètres et 100 ms

Les recherches spatiales et les deux contrôles de distance avant chaque action utilisent 2 m pour les cadavres, objets et contenants. La cadence programmée est de 100 ms depuis le début du passage précédent, sans rattrapage. Le budget reste de 8 ms entre appels natifs.

- **64 scénarios natifs réussis** : les 54 régressions précédentes, neuf cas de frontière/déplacement pour les trois types de source, et un abandon concurrent après initialisation du vecteur mais avant recherche.
- Sur les 64 snapshots, le prochain délai Tick vaut exactement début + 100 ms ; le délai QPC vaut exactement `ceil(fréquence × 100 / 1000)` après le début. Cette vérification détecte un ordonnancement resté à 250 ms sans imposer de plafond au retard de planification de Windows.
- Cas normal hors jeu dans l'installation neuve : 20 intervalles QPC réels, de 106,8986 à 129,7598 ms. Le cas d'appel lent de 320 ms et l'absence de rattrapage restent vérifiés.
- **11 tests hôte et 53 tests complémentaires** réussis. Le script d'arrêt attend maintenant la sortie de l'hôte avant d'autoriser une relance ; le test avec un hôte temporaire qui met 800 ms à finir échoue avec l'ancien script et réussit avec le nouveau. Les formats de date Windows PowerShell et PowerShell 7 sont couverts.

Le jeu étant fermé et le joueur indisponible pour le relancer, **aucune mesure en partie à 2 m / 100 ms n'a été faite**. Les résultats en partie ci-dessous proviennent du réglage précédent 5 m / 250 ms et sont conservés comme historique. Le rayon est une distance sans test de visibilité : il ne bloque pas les prises à travers toutes les cloisons.

## Réalisé en partie sur la première implémentation

- Appel du dispatcher normal du joueur, sans touche de fouille ni visée requise.
- Crédit de 5 unités d'argent de l'ancien monde confirmé par le joueur.
- Plusieurs transitions de cadavres contenant du butin vers un contenu nul et l'état fouillé.
- Cadavre initialement vide : état fouillable → état fouillé, en conservant la sélection native de l'action.
- Fouille automatique d'un nouveau cadavre à 4,536854 mètres ; appel mesuré à 0,4353 ms.
- Restauration des hooks, déchargement normal de QuickJS et détachement vérifiés à chaque essai terminé.

Ces résultats concernent la version Steam 1.7.1.0na, build 25361591.

## Boucle résidente vérifiée en partie le 18 octobre 2026

- Essai de 15 secondes : 59 passages, 59 recherches spatiales et 59 destructions du vecteur natif.
- Cadence QPC réelle : minimum 253,803 ms, maximum 265,6259 ms, moyenne 254,5445 ms.
- Une fouille native a fait passer le contenu d'un cadavre de 2 éléments à zéro ; appel mesuré à 0,7103 ms.
- Le retrait du hook, le déchargement normal du script et le détachement ont réussi sans erreur.
- Après activation continue, neuf fouilles terminées ont été enregistrées. Le joueur a confirmé le butin reçu et un jeu fluide.

## Objets standard au sol

Premier essai en partie le 18 octobre 2026, après qualification de neuf scénarios natifs spécifiques aux objets :

- Découverte de quatre sources `ContainerItem` au sol, avec récepteur, GUID d'action et générations de composants vérifiés.
- Un seul appel du dispatcher normal du joueur, action 1 sélectionnée et autorisée par le jeu, source à 3,832 m.
- Bit natif « consommé » passé de 0 à 1 sans invalidation de la source ; appel mesuré à 0,4973 ms, passage entier à 0,5673 ms.
- Plafond d'un appel respecté et retrait, déchargement, détachement terminés sans erreur.

L'essai continu suivant a effectué 12 passages et trois ramassages, à environ 1,55 m, 1,91 m et 0,26 m. Les trois sources sont passées à l'état natif consommé, sans invalidation. Les appels ont duré 0,5333 ms, 0,4402 ms et 0,4554 ms ; la cadence QPC était comprise entre 252,4129 et 269,4153 ms, sans dépassement du budget. Retrait, déchargement et détachement ont réussi sans erreur.

Le joueur a confirmé la fluidité puis le fonctionnement sur d'autres objets. La boucle cadavres + objets, laissée active à sa demande, a ensuite traité trois nouveaux cadavres et onze objets au sol, sans arrêt natif ni dépassement de budget sur le relevé. Le bit consommé et le retour de l'appel ne mesurent pas directement le crédit d'inventaire ; aucun relevé chiffré de ce crédit n'a été fait pour les composants. Les armes n'ont pas encore été exercées en partie.

L'admissibilité conserve la sélection native et `CanUse`. Seule l'action 1 est acceptée avec un contexte groupe 0, flags `0x20` ; si l'inventaire refuse entre la sélection initiale et l'appel final, le dispatcher rejette l'action 24. Les fixtures couvrent les deux refus. Les routes supplémentaires de redirection sont refusées.

## Sacs et contenants fouillables

Essai en partie du 18 octobre 2026, confirmé par le joueur :

- Source exacte `Container` à 1,179 m, état 1, trois descripteurs de butin, mode local 1, sans enfant ni redirection.
- Route CBS, générations, droit natif de fouille, flag TakeAll déjà actif et interface ILoot vérifiés avant l'appel. Aucun flag n'a été forcé.
- Un seul appel du dispatcher normal, action 1 : contenu 3 → 0, état fouillé 5 ; appel mesuré à 1,2924 ms.
- Plafond d'un appel respecté ; retrait du hook, déchargement et détachement réussis sans erreur.
- Le joueur a confirmé le ramassage. Le lanceur active désormais cadavres, objets et contenants compatibles dans la même boucle.

Ce parcours concerne le `Container` déjà fouillable en état 1, mode local 1. L'ouverture séparée d'un `ComplexContainer`, les serrures et les autres actions restent exclues de cette version. Les trois types de source possèdent des compteurs distincts.

## Qualification hors jeu de la boucle résidente

Qualification actuelle : **64 scénarios réussis** (54 régressions, neuf cas de frontière/déplacement, un abandon concurrent avant recherche), générés par `tools/autoloot_runtime.py --dummy` pendant l'installation. Le cœur C réel est exécuté dans un processus de test dédié, avec les fonctions du moteur remplacées par des stubs natifs. Les chiffres de cadence du tableau proviennent de la qualification initiale des cadavres à 250 ms.

| Scénario | Résultat mesuré |
| --- | --- |
| Arrivées continues de nouveaux cadavres | 10 passages, 10 recherches spatiales, 20 appels de fouille, 20 états fouillés |
| Cadence de ces passages, horloge QPC réelle | 253,54 à 280,23 ms entre débuts de passage |
| Passage normal, horloge QPC réelle | 256,59 à 281,65 ms |
| Appel spatial volontairement lent de 320 ms | 6 passages, aucun ramassage après épuisement du budget ; aucun rattrapage en rafale |
| Gardes | Rayon, identité, génération du handle, propriété du composant, contenu vide, refus et inventaire sans progression |
| Cycle de vie | Arrêts pendant recherche, fouille ou destruction ; concurrence ; changement de personnage |
| Bornes | Pagination, limite de lectures, journaux circulaires et saturation du cache de temporisation |
| Objets au sol | Un ramassage maximal, arrivées continues, refus d'échange avant et pendant le dispatcher, routes redirigées refusées, source consommée, arrêt pendant l'appel, génération du receiver et absence de progression |
| Contenants | Collecte plafonnée, refus d'état/action/flag/mode/enfant/forward/ILoot/contexte, arrêts pendant sélection ou collecte, absence de progression, option inactive et exclusion de ComplexContainer |

Tous ces scénarios vérifient la restauration du point d'entrée, la fin des workers, les registres conservés et l'équilibre allocation/destruction du vecteur. Le test de saturation des journaux utilise une horloge accélérée ; **il n'entre pas dans les chiffres de cadence réelle ci-dessus**.

La commande `--dummy` exécute également **11 tests du cycle de vie Python** : verrou d'instance, arrêt pendant le démarrage, drainage avant détachement, écriture d'état temporairement bloquée, fermeture du processus, arrêt natif signalé comme erreur et plafond de dispatch atteint sans erreur. Les tests supplémentaires contrôlent les chemins Steam, les dépendances publiées, les commandes d'installation, l'identifiant de lancement indépendant du PID du redirecteur Python Windows et l'attente de fin de processus par le script d'arrêt.

Le wrapper JavaScript de production est relu séparément : les 64 scénarios natifs ne prétendent pas exécuter son branchement dans le jeu à la nouvelle cadence. Les essais historiques en partie décrits plus haut exercent le branchement précédent.

## Installation neuve du réglage actuel avant la surveillance automatique

Un export des 30 fichiers publiés a été vérifié contre l'index Git, puis installé dans un dossier neuf, sans `.venv`, `.deps`, preuves ou sauvegardes préexistantes.

- `Installer-AutoLoot.ps1` exécuté sous Windows PowerShell : nouvel environnement Python, installation des trois versions épinglées, **63 scénarios natifs et 11 tests hôte réussis**, code de sortie 0.
- Les **20 tests complémentaires** passent depuis cet environnement neuf, sans test ignoré, y compris l'arrêt drainant sous Windows PowerShell et PowerShell 7.
- Les empreintes du cœur et de sa fixture correspondent aux fichiers de cette installation. Les différences de fins de ligne entre dépôt et dossier de développement n'utilisent aucune qualification périmée.
- Le lanceur réel, jeu fermé, refuse l'activation avec le message « AutoLoot non actif : game_closed Le jeu est fermé », code de sortie 1. Aucun jeu n'a été lancé et aucun script natif n'a été chargé dans le jeu.
- Le guide correspond aux noms et arguments des scripts ; mise à jour dans un dossier neuf après arrêt de l'ancien hôte, réglages 2 m / 100 ms et nom de journal historique explicités.

## Surveillance et installation silencieuse

La surveillance vérifie la présence du jeu toutes les 10 secondes. Avant un nouveau worker, elle attend une découverte complète en lecture seule. Pendant son activité, elle conserve l’identité du processus et l’hôte réel, sans refaire la découverte sur un point déjà modifié par le runtime. Le cœur natif conserve le réglage 2 m / 100 ms.

- **53 tests complémentaires réussis**, dont 25 pour la surveillance : absence du jeu, attente de partie, pause/reprise entre deux passages, arrêt plus récent qu’une reprise, recyclage de PID, redirecteur Python et véritable hôte, drainage et refus de lancement si le statut ne peut pas être publié.
- Les scripts Windows réels vérifient le raccourci COM dans un dossier isolé, l’attente de fin du watcher et du runtime, le refus d’une mise à jour après échec d’arrêt et le remplacement d’un watcher encore vivant après publication d’une erreur.
- Les cinq entrées VBS ont été exercées sous Windows Script Host avec actions inoffensives : succès et échec remontés, PowerShell caché dès le lancement. Les notifications ont été enregistrées par la fixture. Un enfant `pythonw` réel lancé par le backend a confirmé une console absente ; son en-tête PE indique le sous-système graphique.
- Une installation neuve des 37 fichiers publiés, sans dépendance ni preuve préexistante, a réussi : **63 scénarios natifs, 11 tests hôte et 47 tests complémentaires**, sans test ignoré. Seul le résolveur du dossier Démarrage a été remplacé dans la copie pour isoler ce test ; les autres scripts sont ceux de l’index publié.
- Le watcher réel est resté en `waiting_game`, sans lancer de worker, sur deux intervalles mesurés de **10,005447 s** et **9,996560 s**. Le désinstalleur réel a terminé le watcher et retiré le raccourci isolé. Le dossier Démarrage réel n’a pas été touché par cette qualification.

L’arrêt manuel pose une pause persistante avant la demande d’arrêt du ramassage. Le runtime lit aussi cette pause avant toute préparation et aux barrières de chargement/supervision : un véritable hôte né après le redirecteur ne peut pas l’effacer comme une ancienne demande. La reprise acquitte les demandes antérieures, et une mise à jour attend la fermeture effective des anciens hôtes. Aucun hôte de jeu n’est terminé de force. Les anciens lanceurs CMD ont été remplacés par les entrées VBS ; au démarrage de Windows, le raccourci lance directement `pythonw`.

La qualification initiale de cette installation utilisait encore l’égalité stricte entre recherches et destructions. Un contrôle ultérieur a reproduit un abandon concurrent valide après initialisation du vecteur inline, avant toute recherche : zéro recherche, une destruction, aucune allocation ni libération de tas, budget non épuisé. La fixture finale distingue les destructions avec recherche et les abandons inline, vérifie l’équilibre des allocations/libérations et refuse les vecteurs inline invalides, recherches doubles et recherches sans destruction. Ce cas utilise une horloge contrôlée pour synchroniser les threads, sans entrer dans les mesures de cadence réelle. Les 64 scénarios ont réussi avec ces contrôles ; le cœur C et le wrapper JavaScript de production sont restés identiques.

## Limites de validation

- La coopération à deux joueurs, les inventaires pleins et les transitions prolongées de session restent à exercer dans le jeu.
- Les objets au sol utilisent le wrapper exact `ContainerItem` ; les contenants utilisent le type exact `Container`, dans le mode local qualifié. Les sous-classes, ouvertures distinctes et la classification générale des objets de quête ou tenus ne sont pas qualifiées.
- Le budget de travail est contrôlé entre appels natifs ; il n'interrompt pas un appel interne du jeu lent.
- Le déclenchement dépend des ticks actifs du joueur ; il ne fournit pas une horloge indépendante du moteur.
- Les fixtures n'exercent que des processus possédés par les tests, jamais un processus de jeu.
- Le démarrage automatique au prochain lancement réel du jeu et une nouvelle ouverture de session Windows restent à observer ; les contrôles de la surveillance utilisent des processus possédés ou le jeu fermé.

## Contrat de mémoire native

Les blocs modifiables du module C sont alloués et conservés par JavaScript, puis fournis comme symboles externes. Cela suit le [contrat mémoire de CModule documenté par Frida](https://frida.re/docs/javascript-api/#cmodule). Leur libération attend le déchargement normal du script ; le module n'est pas détruit de force pendant un appel.
