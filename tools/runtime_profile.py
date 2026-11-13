"""Adresses des versions qualifiées, séparées des champs et des contrôles."""
import copy
import hashlib
import json
import math
import re


PROFILE_171 = {
    'id': '1.7.1.0na',
    'hashes': {
        'game': 'ddb68c8f87ba2afd0e561b2d1adb9235467c29069fb1cd1619db81e1056378eb',
        'engine': '3dcae152c002f1d549df2ed12c21cc38ddb6b25fd989345f0c413c7442243f1b',
    },
    'rvas': {
        'GAME_PLAYER_UPDATE': 0x12cc7a0,
        'GAME_PLAYER_DISPATCH': 0x12d9aa0,
        'GAME_VECTOR_DESTRUCTOR': 0x1731f0,
        'GAME_CONTEXT_CTOR': 0x1727890,
        'GAME_GET_ACTION': 0xca1ac0,
        'GAME_CAN_USE': 0xc88470,
        'ENGINE_FIND_RADIUS': 0xf3ab0,
        'ENGINE_RADIUS_IMPL': 0xb812c0,
        'ENGINE_GET_LEVEL': 0x82e3d0,
        'ENGINE_GET_COMPONENT': 0x4515c0,
        'ENGINE_CONTROL_TYPE_SLOT': 0x260ebf8,
        'GAME_CBS_POOL_SLOT': 0x37069b0,
        'GAME_PRIMARY': 0x259fe08,
        'GAME_PLAYER_PRIMARY': 0x259c450,
        'GAME_PLAYER_IGS': 0x259d100,
        'GAME_BODY_PRIMARY': 0x29e84f0,
        'GAME_BODY_CONTROL': 0x29e8c38,
        'GAME_BODY_IGS': 0x29e8f10,
        'GAME_BODY_LOOT': 0x29e9950,
        'GAME_HUMAN_PRIMARY': 0x2962618,
        'GAME_COMPONENT_PRIMARY': 0x293c8c0,
        'GAME_STRATEGY_PRIMARY': 0x2a6fda0,
        'GAME_STRATEGY_CALLBACK_2E8': 0x147e190,
        'GAME_STRATEGY_CALLBACK_2F0': 0x149dd40,
        'GAME_STRATEGY_CALLBACK_308': 0x1492690,
        'GAME_ITEM_PRIMARY': 0x29ec228,
        'GAME_ITEM_CONTROL': 0x29ec8f0,
        'GAME_ITEM_IGS': 0x29ecbc8,
        'GAME_CONTAINER_PRIMARY': 0x29e6ff8,
        'GAME_CONTAINER_CONTROL': 0x29e7730,
        'GAME_CONTAINER_IGS': 0x29e7a08,
        'GAME_CONTAINER_LOOT': 0x29e8448,
        'GAME_DROPPED_PRIMARY': 0x296ed88,
        'GAME_DROPPED_CONTROL': 0x296f460,
        'GAME_DROPPED_IGS': 0x296f738,
        'GAME_PROXY_PRIMARY': 0x2d326f8,
        'GAME_MODEL_PROXY_PRIMARY': 0x2d326f8,
        'GAME_PROXY_TARGET_THUNK': 0x24ec9b6,
        'GAME_PROXY_TARGET_IMPORT': 0x257b948,
        'ENGINE_PROXY_TARGET': 0xfba70,
        'GAME_SENDER_TABLE': 0x27ecf30,
        'GAME_RECEIVER_TABLE': 0x27ecee0,
        'GAME_GROUND_MESSAGE_WRAPPER': 0x80cb40,
        'GAME_RECEIVER_CALLBACK_5313': 0x16e8c20,
        'GAME_RECEIVER_CALLBACK_CBBF': 0x16e9040,
        'GAME_RECEIVER_CALLBACK_5F2B': 0x16e8cd0,
        'GAME_INVENTORY_CONTEXT_TABLE': 0x289aaf0,
        'GAME_OPPORTUNITY_FLAG': 0xa305a0,
        'GAME_OPPORTUNITY_FALSE': 0x174c40,
        'GAME_OPPORTUNITY_CONTEXT': 0xa305b0,
        'GAME_BAG_CAN_USE': 0x1121590,
        'GAME_BAG_TAKE': 0x11936c0,
        'GAME_GROUND_TAKE': 0x11944b0,
        'GAME_DROPPED_CAN_USE': 0xd6c570,
        'GAME_DROPPED_TAKE': 0xdee670,
        'GAME_DROPPED_INVENTORY_TAKE': 0xe1a1c0,
        'GAME_CONTAINER_CAN_USE': 0x1121810,
        'GAME_CONTAINER_TAKE': 0x1194280,
        'GAME_CONTAINER_TAKE_ALL': 0x1185870,
    },
}

PROFILE_181 = {
    'id': '1.8.1.0na',
    'experimental': False,
    'hashes': {
        'game': '4f421509f28881c4dd8a744c06d5ccab28017422224809814eeaef127dd075a1',
        'engine': '000fcc064bd512a93cb2eaa6da5f34dcba4e792ba636a897a4630b5637d2c0d4',
    },
    # Adresses exactes de la version prise en charge.
    'rvas': {
        'GAME_PLAYER_UPDATE': 0x12d9530,
        'GAME_PLAYER_DISPATCH': 0x12e6830,
        'GAME_VECTOR_DESTRUCTOR': 0x173e30,
        'GAME_CONTEXT_CTOR': 0x173c250,
        'GAME_GET_ACTION': 0xcac890,
        'GAME_CAN_USE': 0xc93240,
        'ENGINE_FIND_RADIUS': 0xe6310,
        'ENGINE_RADIUS_IMPL': 0xb71770,
        'ENGINE_GET_LEVEL': 0x81ea40,
        'ENGINE_GET_COMPONENT': 0x442830,
        'ENGINE_CONTROL_TYPE_SLOT': 0x25e7fa0,
        'GAME_CBS_POOL_SLOT': 0x373ee80,
        'GAME_PRIMARY': 0x25c5fa8,
        'GAME_PLAYER_PRIMARY': 0x25c25f0,
        'GAME_PLAYER_IGS': 0x25c32a0,
        'GAME_BODY_PRIMARY': 0x2a12168,
        'GAME_BODY_CONTROL': 0x2a128b0,
        'GAME_BODY_IGS': 0x2a12b88,
        'GAME_BODY_LOOT': 0x2a135c8,
        'GAME_HUMAN_PRIMARY': 0x298cd88,
        'GAME_COMPONENT_PRIMARY': 0x2967040,
        'GAME_STRATEGY_PRIMARY': 0x2a98770,
        'GAME_STRATEGY_CALLBACK_2E8': 0x148b640,
        'GAME_STRATEGY_CALLBACK_2F0': 0x14aafc0,
        'GAME_STRATEGY_CALLBACK_308': 0x149f910,
        'GAME_ITEM_PRIMARY': 0x2a16430,
        'GAME_ITEM_CONTROL': 0x2a16af8,
        'GAME_ITEM_IGS': 0x2a16dd0,
        'GAME_CONTAINER_PRIMARY': 0x2a10c70,
        'GAME_CONTAINER_CONTROL': 0x2a113a8,
        'GAME_CONTAINER_IGS': 0x2a11680,
        'GAME_CONTAINER_LOOT': 0x2a120c0,
        'GAME_DROPPED_PRIMARY': 0x29995e0,
        'GAME_DROPPED_CONTROL': 0x2999cb8,
        'GAME_DROPPED_IGS': 0x2999f90,
        'GAME_PROXY_PRIMARY': 0x2d5c2c0,
        'GAME_MODEL_PROXY_PRIMARY': 0x2d5cc10,
        'GAME_PROXY_TARGET_THUNK': 0x251275c,
        'GAME_PROXY_TARGET_IMPORT': 0x25a17d0,
        'ENGINE_PROXY_TARGET': 0xee2d0,
        'GAME_SENDER_TABLE': 0x2813cb0,
        'GAME_RECEIVER_TABLE': 0x2813c60,
        'GAME_GROUND_MESSAGE_WRAPPER': 0x8120f0,
        'GAME_RECEIVER_CALLBACK_5313': 0x16fadd0,
        'GAME_RECEIVER_CALLBACK_CBBF': 0x16fb1f0,
        'GAME_RECEIVER_CALLBACK_5F2B': 0x16fae80,
        'GAME_INVENTORY_CONTEXT_TABLE': 0x28b6630,
        'GAME_OPPORTUNITY_FLAG': 0xa395d0,
        'GAME_OPPORTUNITY_FALSE': 0x175880,
        'GAME_OPPORTUNITY_CONTEXT': 0xa395e0,
        'GAME_BAG_CAN_USE': 0x112da00,
        'GAME_BAG_TAKE': 0x119f830,
        'GAME_GROUND_TAKE': 0x11a0620,
        'GAME_DROPPED_CAN_USE': 0xd78dd0,
        'GAME_DROPPED_TAKE': 0xdfadb0,
        'GAME_DROPPED_INVENTORY_TAKE': 0xe245e0,
        'GAME_CONTAINER_CAN_USE': 0x112dc80,
        'GAME_CONTAINER_TAKE': 0x11a03f0,
        'GAME_CONTAINER_TAKE_ALL': 0x1191e40,
    },
}


def select_profile(game_hash, engine_hash):
    """Une paire d'empreintes inconnue ne réutilise jamais les anciennes adresses."""
    for profile in (PROFILE_171, PROFILE_181):
        if profile['hashes'] == {'game': game_hash, 'engine': engine_hash}:
            if set(profile['rvas']) != set(PROFILE_171['rvas']):
                raise ValueError('Runtime profile incomplete; no legacy address fallback')
            return copy.deepcopy(profile)
    raise ValueError('No reviewed runtime profile for this exact game/engine pair')


def profile_by_name(name):
    for profile in (PROFILE_171, PROFILE_181):
        if name in (profile['id'], profile['id'].removesuffix('.0na')):
            return select_profile(profile['hashes']['game'], profile['hashes']['engine'])
    raise ValueError('Unknown runtime profile: ' + name)


def make_trial_181(profile, duration, diagnostic_only=False, category='corpses', dispatch_cap=1):
    """Créer un contrat d'essai borné pour la version 1.8.1 exacte."""
    if type(duration) not in (int, float) or not 0 < duration <= 30 or not math.isfinite(duration):
        raise ValueError('Trial181 duration must be finite and within (0,30] seconds')
    duration_ms = int(duration * 1000)
    if not 1 <= duration_ms <= 30000:
        raise ValueError('Trial181 duration must remain positive in whole milliseconds')
    if type(diagnostic_only) is not bool:
        raise ValueError('Trial181 diagnostic mode must be boolean')
    if category not in ('corpses', 'ground', 'dropped', 'containers') or (diagnostic_only and category != 'corpses'):
        raise ValueError('Trial181 category differs; diagnosis permits corpses only')
    if type(dispatch_cap) is not int or (dispatch_cap != 0 if diagnostic_only else not 1 <= dispatch_cap <= 64):
        raise ValueError('Trial181 dispatch cap must be zero for diagnosis or an integer1..64 for collection')
    trial = {'kind': 'bounded_trial_181_v1', 'profile_id': PROFILE_181['id'],
             'hashes': dict(PROFILE_181['hashes']), 'duration_ms': duration_ms,
             'mode': 'diagnostic-only' if diagnostic_only else 'collect', 'category': category, 'dispatch_cap': dispatch_cap}
    require_live_profile(profile, trial, 'trial-181')
    return trial


def require_live_profile(profile, trial=None, execution_mode=None):
    if profile not in (PROFILE_171, PROFILE_181):
        raise ValueError('Exact reviewed profile and hash pair required')
    if trial is not None:
        if execution_mode != 'trial-181' or profile != PROFILE_181 or type(trial) is not dict or set(trial) != {'kind', 'profile_id', 'hashes', 'mode', 'category', 'duration_ms', 'dispatch_cap'}:
            raise ValueError('Trial181 requires the exact 1.8.1 profile, mode and contract')
        if trial['kind'] != 'bounded_trial_181_v1' or trial['profile_id'] != PROFILE_181['id'] or trial['hashes'] != PROFILE_181['hashes']:
            raise ValueError('Trial181 profile identity differs')
        if trial['mode'] not in ('diagnostic-only', 'collect') or type(trial['duration_ms']) is not int or not 1 <= trial['duration_ms'] <= 30000:
            raise ValueError('Trial181 mode or canonical duration differs')
        if trial['category'] not in ('corpses', 'ground', 'dropped', 'containers') or (trial['mode'] == 'diagnostic-only' and trial['category'] != 'corpses'):
            raise ValueError('Trial181 category differs; diagnosis permits corpses only')
        if type(trial['dispatch_cap']) is not int or (trial['dispatch_cap'] != 0 if trial['mode'] == 'diagnostic-only' else not 1 <= trial['dispatch_cap'] <= 64):
            raise ValueError('Trial181 dispatch cap differs')
        return
    if execution_mode != 'resident' or profile.get('experimental') is True:
        raise ValueError('Reviewed resident execution mode required')


def profile_digest(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def compiled_core(source, profile=None):
    profile = PROFILE_171 if profile is None else profile
    rvas = profile['rvas']
    required = set(re.findall(r'\bRVA_([A-Z][A-Z0-9_]*)\b', source))
    if not required <= rvas.keys():
        raise ValueError('Runtime profile lacks required addresses: ' + ', '.join(sorted(required - rvas.keys())))
    if set(rvas) != set(PROFILE_171['rvas']) or any(type(value) is not int or not 0 < value < 0x100000000 for value in rvas.values()):
        raise ValueError('Runtime profile address schema differs from the reviewed contract')
    header = '/* Profil exact du runtime : ' + profile_digest(profile) + ' */\n'
    header += ''.join(f'#define RVA_{name} 0x{value:x}\n' for name, value in sorted(rvas.items()))
    return header + source


def fixture_image_size(profile):
    # La fixture partage une image fictive pour les deux modules, avec la place des slots.
    return (max(profile['rvas'].values()) + 0x2fff) & ~0xfff
