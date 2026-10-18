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
2. Double-cliquer sur **Installer-AutoLoot.vbs**. L’installation reste silencieuse ; attendre le message de réussite. En cas d’erreur, le message indique le journal à consulter.
3. Lancer le jeu et **charger une partie**. AutoLoot démarre automatiquement, avec une détection toutes les **10 secondes**. Se déplacer normalement : les sources admissibles dans les 2 mètres sont récupérées automatiquement.

Rien à relancer manuellement : la surveillance démarre aussi à l’ouverture de Windows. Elle attend en arrière-plan quand le jeu est fermé ; le ramassage s’arrête avec le jeu. Le démarrage normal utilise directement **pythonw**, sans fenêtre de console. Garder le dossier installé à sa place : le raccourci de démarrage pointe vers lui.

## Arrêter et mettre à jour

Pour suspendre le ramassage, double-cliquer sur **Arreter-AutoLoot.vbs**. La pause est conservée après fermeture du jeu et redémarrage de Windows. Pour reprendre le fonctionnement automatique, utiliser **Lancer-AutoLoot.vbs** une seule fois. L’arrêt attend la fin de l’appel du jeu éventuellement en cours ; un dépassement du délai est signalé sans tuer Python.

Pour une mise à jour :

1. Télécharger et extraire la nouvelle version dans un dossier neuf.
2. Exécuter son **Installer-AutoLoot.vbs** : il arrête l’installation automatique précédente, refait les contrôles puis remplace son raccourci de démarrage.
3. Après le message de réussite, l’ancien dossier peut être supprimé. Pour une ancienne version à lancement manuel, l’arrêter d’abord avec son propre script d’arrêt.

Pour désinstaller, exécuter **Desinstaller-AutoLoot.vbs** depuis le dossier actif, attendre la confirmation puis supprimer ce dossier. Cela arrête la surveillance et retire son raccourci du dossier Démarrage de Windows. Aucun fichier du jeu n’a été remplacé.

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
| Python ou dépendances introuvables | Installer Python 64 bits, puis refaire Installer-AutoLoot.vbs. |
| Jeu introuvable ou partie non chargée | Charger une partie ; vérifier le chemin ci-dessus. |
| Version du jeu non prise en charge | Conserver le refus ; ne pas retirer les contrôles de version. |
| Une instance est déjà active | Ne pas lancer plusieurs dossiers. Installer la nouvelle version pour remplacer l’ancienne surveillance. |
| Contrôles hors jeu absents ou périmés après une mise à jour | Refaire Installer-AutoLoot.vbs dans le nouveau dossier. |
| Pas de butin | Vérifier la distance, le caractère fouillable et la place disponible. Un cadavre peut être vide ; certaines interactions restent exclues. |
| Besoin de suspendre le mod | Utiliser Arreter-AutoLoot.vbs ; les ticks de tous les menus et états de pause ne sont pas qualifiés. |
| Aucun démarrage automatique | Vérifier que le dossier installé existe encore, que Windows autorise son raccourci dans Démarrage, puis consulter `evidence/autoloot5m/watch-status.json`. |
| Les fichiers VBS ne s’ouvrent pas | Windows Script Host doit être disponible. Sur un PC où il est désactivé par une politique système, cette installation silencieuse ne peut pas fonctionner. |

Pour refaire les contrôles hors jeu sans lancer le mod, utiliser **Verifier-AutoLoot.vbs**. Cette vérification n’appelle aucune fonction du jeu.

Les journaux restent locaux dans `evidence/autoloot5m/`. Ce nom de dossier est historique : **le rayon actuel est bien de 2 m**. Utiliser le script d’arrêt avant de déplacer ou remplacer le dossier.

## Développement

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\autoloot_runtime.py --dummy
```

Les fixtures exécutent le cœur natif dans un processus de test dédié. Elles vérifient la cadence programmée, les limites de distance, les refus et le retrait des hooks ; elles ne prouvent pas à elles seules un crédit d’inventaire ou le fonctionnement en coopération.

Le dépôt ne contient aucun exécutable ou DLL du jeu, sauvegarde, capture mémoire ou dépendance binaire vendue avec le jeu.
