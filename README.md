# AutoLoot — Dying Light: The Beast

Prototype Windows pour fouiller automatiquement les cadavres, les sacs et contenants compatibles, et ramasser les composants au sol à **5 mètres**, sans viser ni appuyer sur une touche.

Le mode résident prévoit un passage toutes les **250 ms** sur les mises à jour du joueur. La distance, la source et l'autorisation de ramassage sont revérifiées avant l'action normale du jeu. Les cadavres initialement vides sont également pris en charge.

## État

- Le ramassage réel a déjà été confirmé en partie : **5 unités d'argent de l'ancien monde** reçues ; une fouille automatique a aussi réussi à **4,54 m**.
- Le mode résident a été confirmé en partie : butin reçu et jeu fluide. Sur un relevé de 15 secondes, les passages étaient espacés de 253,80 à 265,63 ms. Voir [les vérifications et leurs limites](docs/VALIDATION.md).
- La coopération conserve le dispatcher du joueur local ; **le résultat à deux joueurs reste à vérifier**.
- Le ramassage des composants au sol est confirmé par le joueur. La boucle combinée a également traité trois nouveaux cadavres et onze objets au sol pendant ses déplacements.
- La fouille d'un sac a été confirmée en partie : ses trois entrées de butin ont été récupérées automatiquement. Le lanceur active aussi les contenants compatibles.
- Le prototype conserve les refus du jeu : il ne force pas l'action d'échange lorsqu'une arme ne peut pas entrer dans l'inventaire. Les armes n'ont pas encore été vérifiées en partie.

Les contenants déjà fouillables sont traités. Les coffres verrouillés ou nécessitant une ouverture distincte restent à ouvrir manuellement.

## Configuration requise

- Windows 64 bits.
- Version Steam **1.7.1.0na**, build **25361591**, de Dying Light: The Beast. Une autre version est refusée.
- [Python 64 bits](https://www.python.org/downloads/windows/), version 3.11 ou plus. Environnement de validation : Python 3.14.
- Connexion Internet pour la première installation des dépendances.

Aucun compilateur ni remplacement de fichier du jeu n'est nécessaire. Les dépendances Python sont installées dans le dossier `.venv` de ce projet.

## Installation

1. Télécharger le dépôt avec **Code → Download ZIP**, puis extraire entièrement l'archive, ou le cloner avec Git.
2. Double-cliquer sur **`Installer-AutoLoot.cmd`**. L'installation crée l'environnement Python et exécute les contrôles hors jeu. Attendre le message de réussite.
3. Lancer le jeu et charger une partie.
4. Double-cliquer sur **`Lancer-AutoLoot.cmd`**. Le message « AutoLoot actif » confirme que le programme est attaché. En cas d'échec, la fenêtre affiche la raison.
5. Se déplacer normalement : les cadavres, sacs et contenants admissibles sont fouillés ; les objets standard ramassables sont récupérés à moins de 5 mètres.

Pour arrêter, double-cliquer sur **`Arreter-AutoLoot.cmd`**. Une action native déjà commencée se termine avant le retrait. Fermer le jeu termine également le programme. Après avoir relancé le jeu, relancer AutoLoot.

Pour refaire les contrôles hors jeu, utiliser **`Verifier-AutoLoot.cmd`**.

### Si le jeu est installé sur un autre disque

Les bibliothèques Steam sont détectées automatiquement. Si nécessaire, copier `autoloot.local.example.json` en `autoloot.local.json` et renseigner le dossier qui contient `ph_ft` :

```json
{
  "game_path": "D:/SteamLibrary/steamapps/common/Dying Light The Beast"
}
```

La variable d'environnement `AUTOLOOT_GAME_PATH` permet aussi d'indiquer ce dossier. Le fichier local et les chemins personnels ne sont pas publiés dans le dépôt.

## Ce que signifie « toutes les 250 ms »

La cadence est mesurée entre les débuts de passage, sans ajouter 250 ms après le traitement. Le déclenchement attend le premier tick disponible du joueur : il dépend donc du rythme du jeu. Les passages manqués ne sont pas rattrapés en rafale.

Le travail par passage est borné. Si beaucoup d'objets sont présents, le traitement restant est reporté aux passages suivants. Un appel interne du jeu déjà commencé n'est jamais interrompu ; une suspension du jeu ou un appel lent peut donc retarder le passage suivant.

La présence ou l'absence de ticks dans tous les menus et états de pause n'est pas encore établie. Utiliser le bouton d'arrêt fourni pour suspendre explicitement le mod.

## Dépannage

| Situation | Action |
| --- | --- |
| Python ou dépendances introuvables | Refaire `Installer-AutoLoot.cmd`. |
| Jeu introuvable | Charger une partie ; vérifier le chemin ci-dessus. |
| Version non prise en charge | Conserver le refus et signaler la version ; ne pas retirer les contrôles de signature. |
| Une instance est déjà active | Utiliser `Arreter-AutoLoot.cmd` avant de relancer. |
| Pas de butin | Vérifier que la source est ramassable et dans le rayon ; un cadavre peut être vide ou l'inventaire plein. Certains objets et interactions ne sont pas pris en charge. |

L'état et les journaux se trouvent dans `evidence/autoloot5m/`. Ils restent locaux. Ne pas arrêter de force Python pendant une action native : utiliser le script d'arrêt.

## Développement

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\autoloot_runtime.py --dummy
```

Les fixtures utilisent un processus de test dédié. Elles vérifient les appels natifs simulés, la cadence, les gardes et le retrait des hooks. Elles ne prouvent pas à elles seules le comportement du jeu ou de la coopération.

Le dépôt contient uniquement le code et sa documentation. Il ne contient aucun exécutable ou DLL du jeu, sauvegarde, capture mémoire ou dépendance binaire vendue avec le jeu.
