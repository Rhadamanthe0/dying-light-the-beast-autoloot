"""Resolve a user-selected or Steam-installed game, without changing it."""
import json
import os
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
RELATIVE_EXE=Path('ph_ft/work/bin/x64/DyingLightGame_TheBeast_x64_rwdi.exe')

def quoted_value(text,key):
    match=re.search(r'"'+re.escape(key)+r'"\s*"((?:\\.|[^"\\])*)"',text,re.IGNORECASE)
    return match.group(1).replace('\\\\','\\').replace('\\"','"') if match else None

def steam_roots():
    result=[]
    for variable in ('PROGRAMFILES(X86)','PROGRAMFILES'):
        if os.environ.get(variable):result.append(Path(os.environ[variable])/'Steam')
    if os.name=='nt':
        import winreg
        for hive,key,value in [(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam','SteamPath'),
                               (winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\WOW6432Node\Valve\Steam','InstallPath')]:
            try:
                with winreg.OpenKey(hive,key) as handle:result.insert(0,Path(winreg.QueryValueEx(handle,value)[0]))
            except OSError:pass
    if not result:result.append(Path('C:/Program Files (x86)/Steam'))
    return list(dict.fromkeys(result))

def locate_game():
    selected=os.environ.get('AUTOLOOT_GAME_PATH')
    local=ROOT/'autoloot.local.json'
    if not selected and local.exists():
        config=json.loads(local.read_text(encoding='utf-8-sig'))
        selected=config.get('game_path')
        if selected is not None and (not isinstance(selected,str) or not selected.strip()):
            raise ValueError('autoloot.local.json: game_path must be a nonempty path')
    if selected:
        path=Path(selected).expanduser().resolve()
        if not (path/RELATIVE_EXE).is_file():
            raise ValueError('Game executable not found under selected game_path: '+str(path))
        return path
    roots=steam_roots();libraries=list(roots)
    for root in roots:
        vdf=root/'steamapps/libraryfolders.vdf'
        try:text=vdf.read_text(encoding='utf-8-sig')
        except OSError:continue
        for match in re.finditer(r'"path"\s*"((?:\\.|[^"\\])*)"',text,re.IGNORECASE):
            libraries.append(Path(match.group(1).replace('\\\\','\\').replace('\\"','"')))
    for library in dict.fromkeys(libraries):
        manifest=library/'steamapps/appmanifest_3008130.acf'
        try:directory=quoted_value(manifest.read_text(encoding='utf-8-sig'),'installdir')
        except OSError:directory=None
        if directory and (Path(directory).is_absolute() or '/' in directory or '\\' in directory or directory in ('.','..')):
            directory=None
        path=library/'steamapps/common'/(directory or 'Dying Light The Beast')
        if (path/RELATIVE_EXE).is_file():return path.resolve()
    # Import remains possible on a test computer without the game installed.
    # A real preflight fails on the missing executable/DLLs.
    return (roots[0]/'steamapps/common/Dying Light The Beast').resolve()
