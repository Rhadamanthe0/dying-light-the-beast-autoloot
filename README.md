# AutoLoot — Dying Light: The Beast

Ramassage automatique des cadavres, composants au sol, sacs et contenants compatibles, sans viser ni appuyer sur une touche.

**Rayon : 2 mètres. Cadence cible : 100 ms.** Les trois types de source utilisent ces mêmes réglages. Le jeu conserve ses contrôles d’admissibilité et de capacité ; le mod ne force pas un échange d’arme.

Le rayon mesure une distance, sans test de visibilité : un objet derrière une cloison fine peut encore être récupéré. Les coffres verrouillés ou nécessitant une ouverture distincte restent à ouvrir manuellement.

## Configuration requise

- Windows 64 bits.
- Version Steam **1.7.1.0na**, build **25361591**, de Dying Light: The Beast. Une autre version est refusée.
- [Python 64 bits](https://www.python.org/downloads/windows/), version 3.11 ou plus ; validation effectuée avec Python 3.14.
- Une connexion Internet pour installer les dépendances la première fois.

Aucun compilateur ni remplacement de fichier du jeu n’est nécessaire. Tout le programme et ses dépendances restent dans ce dossier.

## Première installation

1. Sur [GitHub](https://github.com/Rhadamanthe0/dying-light-the-beast-autoloot), choisir **Code → Download ZIP**, puis extraire entièrement l’archive dans un dossier accessible en écriture. Ne pas lancer les fichiers directement depuis le ZIP.
2. Double-cliquer sur **Installer-AutoLoot.cmd**. Attendre « Installation et controles hors jeu termines ». Une fenêtre qui affiche une erreur ne confirme pas l’installation : corriger la cause indiquée avant de continuer.
3. Lancer le jeu et **charger une partie**.
4. Double-cliquer sur **Lancer-AutoLoot.cmd**. Attendre « AutoLoot actif », avec **2 m** et **100 ms**. Le chargement de la partie doit être terminé.
5. Se déplacer normalement : les sources admissibles dans les 2 mètres sont récupérées automatiquement.

Le programme fonctionne en arrière-plan après ce message. Fermer le jeu l’arrête. Après chaque relance du jeu, utiliser de nouveau **Lancer-AutoLoot.cmd**.

## Arrêter et mettre à jour

Pour arrêter, double-cliquer sur **Arreter-AutoLoot.cmd** et attendre **« AutoLoot arrete »**. Le programme termine d’abord l’appel du jeu éventuellement en cours. Si l’arrêt dépasse 30 secondes, le script le signale sans tuer Python : attendre sa fin avant de relancer.

Pour une mise à jour :

1. Arrêter l’ancienne version **depuis son dossier**, comme indiqué ci-dessus. Si aucun hôte actif n’est identifié, le script l’indique ; ne pas confondre ce message avec une fin de drainage confirmée.
2. Télécharger et extraire la nouvelle version dans un dossier neuf.
3. Exécuter son **Installer-AutoLoot.cmd**, même si une ancienne version était déjà installée. Les contrôles doivent correspondre au code téléchargé.
4. Charger une partie, puis exécuter le nouveau **Lancer-AutoLoot.cmd**.

Pour désinstaller, arrêter AutoLoot puis supprimer son dossier. Aucun fichier du jeu n’a été remplacé.

## Si le jeu est installé sur un autre disque

Les bibliothèques Steam sont détectées automatiquement. En cas d’échec, copier **autoloot.local.example.json** en **autoloot.local.json** et indiquer le dossier qui contient `ph_ft` :

```json
{
  "game_path": "D:/SteamLibrary/steamapps/common/Dying Light The Beast"
}
```

La variable d’environnement `AUTOLOOT_GAME_PATH` permet aussi d’indiquer ce dossier. Le fichier de configuration local et les chemins personnels ne sont pas publiés.

## Cadence et état de validation

Les 100 ms sont mesurées depuis le début du passage précédent, sans ajouter ce délai après le traitement. Le déclenchement attend le premier tick disponible du joueur. Une pause, un ralentissement ou un appel interne du jeu peuvent retarder le passage suivant ; aucun rattrapage en rafale n’est effectué. Si beaucoup de sources sont présentes, leur traitement est réparti sur plusieurs passages.

Les cadavres, composants et sacs ont été confirmés en partie avec l’ancien réglage 5 m / 250 ms. Le nouveau réglage 2 m / 100 ms est vérifié hors jeu ; sa cadence réelle dans le jeu reste à mesurer. La coopération conserve le dispatcher du joueur local, mais le résultat à deux joueurs et les armes n’ont pas encore été vérifiés en partie. Voir [les vérifications et leurs limites](docs/VALIDATION.md).

## Dépannage

| Situation | Action |
| --- | --- |
| Python ou dépendances introuvables | Installer Python 64 bits, puis refaire Installer-AutoLoot.cmd. |
| Jeu introuvable ou partie non chargée | Charger une partie ; vérifier le chemin ci-dessus. |
| Version du jeu non prise en charge | Conserver le refus ; ne pas retirer les contrôles de version. |
| Une instance est déjà active | Utiliser Arreter-AutoLoot.cmd dans le dossier qui l’a lancée, attendre la fin, puis relancer. |
| Contrôles hors jeu absents ou périmés après une mise à jour | Refaire Installer-AutoLoot.cmd dans le nouveau dossier. |
| Pas de butin | Vérifier la distance, le caractère fouillable et la place disponible. Un cadavre peut être vide ; certaines interactions restent exclues. |
| Besoin de suspendre le mod | Utiliser Arreter-AutoLoot.cmd ; les ticks de tous les menus et états de pause ne sont pas qualifiés. |

Pour refaire les contrôles hors jeu sans lancer le mod, utiliser **Verifier-AutoLoot.cmd**. Cette vérification n’appelle aucune fonction du jeu.

Les journaux restent locaux dans `evidence/autoloot5m/`. Ce nom de dossier est historique : **le rayon actuel est bien de 2 m**. Utiliser le script d’arrêt avant de déplacer ou remplacer le dossier.

## Développement

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\autoloot_runtime.py --dummy
```

Les fixtures exécutent le cœur natif dans un processus de test dédié. Elles vérifient la cadence programmée, les limites de distance, les refus et le retrait des hooks ; elles ne prouvent pas à elles seules un crédit d’inventaire ou le fonctionnement en coopération.

Le dépôt ne contient aucun exécutable ou DLL du jeu, sauvegarde, capture mémoire ou dépendance binaire vendue avec le jeu.
