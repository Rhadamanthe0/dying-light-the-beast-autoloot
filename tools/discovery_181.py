"""Qualification statique stricte de la version prise en charge 1.8.1."""
import hashlib
import re
import struct

from inspect_native import Image
from runtime_profile import PROFILE_181


FUNCTIONS = {
    'PlayerUpdate': (0x12d9530, '40534883ec4080b9003c000000488d81'),
    'PlayerDispatch': (0x12e6830, '4885d20f84db00000048895c24104889'),
    'BodyAction': (0x119f830, '4055564154415541564881ecd0010000'),
    'TransferHelper': (0x1192040, '40564154415541574883ec780fb681cf'),
    'Tick': (0x103dc70, '40534883ec300f29742420488bd90f28'),
    'Game_coop_count': (0x15bf200, '40534883ec20488b01488bd9ff905008'),
    'Game_session_present': (0x1780f0, '4883b938010000000f95c0c3cccccccc'),
    'Session_context_getter': (0x15be2c0, '488b8108160000c3cccccccccccccccc'),
    'Context_coop_count': (0x15c0a10, '0fb681d723000084c075078b81d82300'),
    'CndIsCoop': (0xddd120, '4883ec28e8871bd6ff488bc8488b10ff'),
    'Game_global_getter': (0xb3ecb0, '488b05b95ffc02c3cccccccccccccccc'),
    'Trigger_owner_getter': (0x180440, '488b4108c3cccccccccccccccccccccc'),
    'Player_controller_host_getter': (0x6e9540, '488b8100020000c3cccccccccccccccc'),
    'Controller_tick_loop': (0x1f09100, '48895c240848896c2410488974241857'),
}


def unique(values, label):
    values = list(values)
    if len(values) != 1:
        raise ValueError(f'{label} absent ou ambigu : {len(values)}')
    return values[0]


def instructions(image, rva, size):
    offset = image.offset(rva)
    return list(image.cs.disasm(image.data[offset:offset + size], image.base + rva))


def direct_call(image, rva, target):
    instruction = unique(instructions(image, rva, 5), 'Appel direct')
    if instruction.mnemonic != 'call' or instruction.operands[0].type != 2 or instruction.operands[0].imm != image.base + target:
        raise ValueError('Cible de l’appel différente : ' + hex(rva))


def rip_target(image, rva, mnemonic, operand):
    instruction = instructions(image, rva, 16)[0]
    memory = instruction.operands[operand].mem
    if instruction.mnemonic != mnemonic or instruction.reg_name(memory.base) != 'rip':
        raise ValueError('Instruction RIP-relative différente : ' + hex(rva))
    return instruction.address + instruction.size + memory.disp - image.base


def exact_table(image, cls, offset, expected):
    table = unique((row for row in image.vtables(cls) if row['subobject_offset'] == offset), 'Table RTTI ' + cls)
    if int(table['vtable_rva'], 0) != expected:
        raise ValueError('Adresse RTTI différente : ' + cls)
    return table


def slot(table, offset, expected):
    if offset % 8 or offset // 8 >= len(table['functions']) or int(table['functions'][offset // 8], 0) != expected:
        raise ValueError('Slot RTTI différent : ' + hex(offset))


def guard_function(image, name, rva, expected, unique_prefix=False, pdata_required=False):
    start = image.offset(rva)
    raw = bytes.fromhex(expected)
    if image.data[start:start + len(raw)] != raw:
        raise ValueError('Préfixe 1.8.1 différent : ' + name)
    if unique_prefix and image.data.count(raw) != 1:
        raise ValueError('Préfixe absent ou ambigu : ' + name)
    function = image.function(rva)
    if (pdata_required and function is None) or (function is not None and function[0] != rva):
        raise ValueError('Début de fonction non qualifié : ' + name)
    return {'name': name, 'rva': rva, 'hex': expected}


def table_proof(image, table):
    rva = int(table['vtable_rva'], 0)
    col = struct.unpack_from('<Q', image.data, image.offset(rva) - 8)[0] - image.base
    raw = image.data[image.offset(col):image.offset(col) + 24]
    signature, offset, _, descriptor, _, self_rva = struct.unpack('<6I', raw)
    if signature != 1 or offset != table['subobject_offset'] or self_rva != col:
        raise ValueError('COL RTTI invalide')
    return {'class': table['class'], 'rva': rva, 'col_rva': col, 'col_hex': raw.hex(),
            'type_descriptor_rva': descriptor, 'rtti_name': '.?AV' + table['class'] + '@@',
            'first_eight_function_rvas': [int(value, 0) for value in table['functions'][:8]]}


def exported(image, name):
    """Parcours borné brut, car le parseur standard tronque cette grande table."""
    directory = image.pe.OPTIONAL_HEADER.DATA_DIRECTORY[0]
    base = image.offset(directory.VirtualAddress)
    count_functions, count_names, functions, names, ordinals = struct.unpack_from('<5I', image.data, base + 20)
    if not 0 < count_functions <= 200000 or not 0 < count_names <= 200000:
        raise ValueError('Table d’exports hors limites')
    matches = []
    for index in range(count_names):
        name_rva = struct.unpack_from('<I', image.data, image.offset(names) + 4 * index)[0]
        start = image.offset(name_rva)
        end = image.data.find(b'\0', start, start + 16384)
        if end < 0:
            raise ValueError('Nom d’export non borné')
        if image.data[start:end] != name.encode('ascii'):
            continue
        ordinal = struct.unpack_from('<H', image.data, image.offset(ordinals) + 2 * index)[0]
        if ordinal >= count_functions:
            raise ValueError('Ordinal hors limites')
        target = struct.unpack_from('<I', image.data, image.offset(functions) + 4 * ordinal)[0]
        if directory.VirtualAddress <= target < directory.VirtualAddress + directory.Size:
            raise ValueError('Export redirigé non qualifié')
        matches.append(target)
    return unique(matches, 'Export ' + name)


def validate_callbacks(image, rvas):
    result = []
    for key, registrar, reference, constructor, guid in [
        ('GAME_RECEIVER_CALLBACK_5313', 0x16fc7f0, 0x16fc8fb, 0x179a840, 0x53139e0185c9a12f),
        ('GAME_RECEIVER_CALLBACK_5F2B', 0x16fc9b0, 0x16fcabb, 0x179a860, 0x5f2b7eb72fee8475),
        ('GAME_RECEIVER_CALLBACK_CBBF', 0x16fd270, 0x16fd37b, 0x179a900, 0xcbbfaec882b2a3ea)]:
        references = []
        for match in re.finditer(rb'\x48\x8d\x05....', image.data, re.DOTALL):
            address = image.rva(match.start())
            displacement = struct.unpack_from('<i', image.data, match.start() + 3)[0]
            if address + 7 + displacement == rvas[key]:
                references.append(address)
        if unique(references, 'Référence du callback') != reference or rip_target(image, reference, 'lea', 1) != rvas[key]:
            raise ValueError('Callback non relié à son registrar')
        function = image.function(reference)
        if not function or function[0] != registrar:
            raise ValueError('Fonction registrar différente')
        decoded = instructions(image, registrar, function[1] - registrar)
        calls = [instruction for instruction in decoded if instruction.mnemonic == 'call' and instruction.operands[0].type == 2
                 and instruction.operands[0].imm == image.base + constructor]
        if len(calls) != 2:
            raise ValueError('Constructeur du GUID non recoupé')
        raw = b'\x48\xb8' + struct.pack('<Q', guid) + bytes.fromhex('488901488bc1c3')
        start = image.offset(constructor)
        if image.data[start:start + len(raw)] != raw:
            raise ValueError('GUID du callback différent')
        listing = [(instruction.mnemonic, instruction.op_str) for instruction in decoded]
        if not all(value in listing for value in [('add', 'rax, 0x20'), ('dec', 'rax')]):
            raise ValueError('Delta du callback non recoupé')
        result.append({'name': key, 'rva': rvas[key], 'hex': image.data[image.offset(rvas[key]):image.offset(rvas[key]) + 32].hex()})
    return result


def prepare_static_181(image, bin_path, hashes):
    if hashes != PROFILE_181['hashes']:
        raise ValueError('Paire d’empreintes 1.8.1 exacte requise')
    if image.pe.FILE_HEADER.Machine != 0x8664 or image.pe.OPTIONAL_HEADER.Magic != 0x20b:
        raise ValueError('PE x64 requis')
    image.cs.detail = True
    rvas = PROFILE_181['rvas']
    engine = Image(bin_path / 'engine_x64_rwdi.dll')
    if hashlib.sha256(engine.data).hexdigest() != hashes['engine']:
        raise ValueError('Le moteur a changé pendant le précontrôle')
    for name, key in [
        ('?GetComponentImpl@ComponentsPool@cbs@@QEAAPEAVCBaseObject@2@W4Handle@detail@2@@Z', 'ENGINE_GET_COMPONENT'),
        ('?m_RTTI@CControlObject@@2AEAVType@rtti@@EA', 'ENGINE_CONTROL_TYPE_SLOT'),
        ('?GetMessagePipeTarget@CoIGSObjectProxy@@UEAAPEAVCRTTIObject@@XZ', 'ENGINE_PROXY_TARGET'),
        ('?FindObjectsInRadius@ILevel@@QEAA_NPEAV?$vector@PEAVIControlObject@@V?$heap_allocator@PEAVIControlObject@@@vector_allocators@ttl@@$00@ttl@@AEBVvec3@@MPEBVType@rtti@@_NPEAH@Z', 'ENGINE_FIND_RADIUS')]:
        if exported(engine, name) != rvas[key]:
            raise ValueError('Export moteur différent : ' + name)
    tables = {}
    for key, cls, expected in [('game', 'GameDI_PH', rvas['GAME_PRIMARY']),
                               ('player', 'PlayerDI_PH', rvas['GAME_PLAYER_PRIMARY']),
                               ('trigger', 'TriggerController', 0x29ee060)]:
        tables[key] = exact_table(image, cls, 0, expected)
    slot(tables['game'], 0x850, FUNCTIONS['Game_session_present'][0])
    slot(tables['game'], 0x880, FUNCTIONS['Game_coop_count'][0])
    slot(tables['trigger'], 0x478, FUNCTIONS['Tick'][0])
    slot(tables['trigger'], 0x4a8, FUNCTIONS['Trigger_owner_getter'][0])
    guards = []
    for name, (rva, expected) in FUNCTIONS.items():
        unique_prefix = name in ('PlayerUpdate', 'PlayerDispatch', 'BodyAction', 'TransferHelper', 'Session_context_getter', 'Context_coop_count', 'Trigger_owner_getter', 'Player_controller_host_getter', 'CndIsCoop', 'Game_global_getter')
        pdata_required = name in ('PlayerUpdate', 'PlayerDispatch', 'BodyAction', 'TransferHelper', 'Tick', 'Game_coop_count', 'Controller_tick_loop')
        guards.append(guard_function(image, name, rva, expected, unique_prefix, pdata_required))
    direct_call(image, 0xddd124, 0xb3ecb0)
    if rip_target(image, 0xb3ecb0, 'mov', 1) != 0x3b04c70:
        raise ValueError('Global Game différent')
    direct_call(image, 0x12d96fc, 0x6e9540)
    direct_call(image, 0x12d9704, 0x1f09100)
    direct_call(image, 0x12d9751, 0x1f098d0)
    if rip_target(image, 0x12e684e, 'mov', 1) != rvas['GAME_CBS_POOL_SLOT']:
        raise ValueError('Global CBS différent')
    if rip_target(image, 0x12e6858, 'call', 0) != 0x259f8c0:
        raise ValueError('Import du composant différent')
    loop = [(instruction.mnemonic, instruction.op_str) for instruction in instructions(image, 0x1f09100, 0xc4)]
    for expected in [('mov', 'rdx, qword ptr [rsi + 0x1c8]'), ('mov', 'rax, qword ptr [rdx + 0x1d8]'), ('mov', 'ecx, dword ptr [rdx + 0x1e0]')]:
        if expected not in loop:
            raise ValueError('Structure du registre des contrôleurs différente')
    tick_call = instructions(image, 0x1f09961, 6)[0]
    if tick_call.mnemonic != 'call' or tick_call.operands[0].mem.disp != 0x478:
        raise ValueError('Slot Tick différent dans le parcours du joueur')
    for cls, keys in [
        ('BodyContainer', {0: 'GAME_BODY_PRIMARY', 0x10: 'GAME_BODY_CONTROL', 0x20: 'GAME_BODY_IGS', 0x3d8: 'GAME_BODY_LOOT'}),
        ('Container', {0: 'GAME_CONTAINER_PRIMARY', 0x10: 'GAME_CONTAINER_CONTROL', 0x20: 'GAME_CONTAINER_IGS', 0x3d8: 'GAME_CONTAINER_LOOT'}),
        ('ContainerItem', {0: 'GAME_ITEM_PRIMARY', 0x10: 'GAME_ITEM_CONTROL', 0x20: 'GAME_ITEM_IGS'}),
        ('DroppedItem', {0: 'GAME_DROPPED_PRIMARY', 0x10: 'GAME_DROPPED_CONTROL', 0x20: 'GAME_DROPPED_IGS'}),
        ('HumanAI', {0: 'GAME_HUMAN_PRIMARY'}), ('CoTriggerable', {0: 'GAME_COMPONENT_PRIMARY'}),
        ('AITriggerStrategy', {0: 'GAME_STRATEGY_PRIMARY'}), ('CoGameObjectProxy', {0: 'GAME_PROXY_PRIMARY'}),
        ('ItemDescWithContext', {0: 'GAME_INVENTORY_CONTEXT_TABLE'})]:
        for offset, key in keys.items():
            exact_table(image, cls, offset, rvas[key])
    for cls, primary_key, pairs in [
        ('BodyContainer', 'GAME_BODY_PRIMARY', [(0x620, 'GAME_BAG_CAN_USE'), (0x628, 'GAME_BAG_TAKE')]),
        ('Container', 'GAME_CONTAINER_PRIMARY', [(0x620, 'GAME_CONTAINER_CAN_USE'), (0x628, 'GAME_CONTAINER_TAKE')]),
        ('ContainerItem', 'GAME_ITEM_PRIMARY', [(0x628, 'GAME_GROUND_TAKE')]),
        ('DroppedItem', 'GAME_DROPPED_PRIMARY', [(0x620, 'GAME_DROPPED_CAN_USE'), (0x628, 'GAME_DROPPED_TAKE')]),
        ('CoGameObjectProxy', 'GAME_PROXY_PRIMARY', [(0x128, 'GAME_PROXY_TARGET_THUNK')])]:
        table = exact_table(image, cls, 0, rvas[primary_key])
        for offset, target_key in pairs:
            slot(table, offset, rvas[target_key])
    dropped_proxy = exact_table(image, 'CoModelObjectProxy', 0, rvas['GAME_MODEL_PROXY_PRIMARY'])
    slot(dropped_proxy, 0x128, rvas['GAME_PROXY_TARGET_THUNK'])
    for cls, key in [('BodyContainer', 'GAME_BODY_LOOT'), ('Container', 'GAME_CONTAINER_LOOT')]:
        slot(exact_table(image, cls, 0x3d8, rvas[key]), 0x20, rvas['GAME_CONTAINER_TAKE_ALL'])
    for cls, key in [
        ('?$PoolMessagePumpPipeIn@VMessagePoolTrigger@@@?$PoolMessagePump@VMessagePoolTrigger@@@msg@cbs', 'GAME_RECEIVER_TABLE'),
        ('?$PoolMessagePipeOut@VMessagePoolTrigger@@@msg@cbs', 'GAME_SENDER_TABLE')]:
        table = exact_table(image, cls, 8, rvas[key])
        if key == 'GAME_RECEIVER_TABLE':
            slot(table, 8, rvas['GAME_GROUND_MESSAGE_WRAPPER'])
    for cls, key in [('ItemDesc', 'GAME_OPPORTUNITY_FALSE'), ('ItemDescInventory', 'GAME_OPPORTUNITY_FALSE'),
                     ('ItemDescWithContext', 'GAME_OPPORTUNITY_CONTEXT'), ('ItemDescWeapon', 'GAME_OPPORTUNITY_FLAG'),
                     ('ItemDescFirearm', 'GAME_OPPORTUNITY_FLAG'), ('ItemDescThrowable', 'GAME_OPPORTUNITY_FLAG')]:
        table = unique((row for row in image.vtables(cls) if row['subobject_offset'] == 0), 'Description inventaire ' + cls)
        slot(table, 0x12a8, rvas[key])
    strategy = exact_table(image, 'AITriggerStrategy', 0, rvas['GAME_STRATEGY_PRIMARY'])
    for offset, key in [(0x2e8, 'GAME_STRATEGY_CALLBACK_2E8'), (0x2f0, 'GAME_STRATEGY_CALLBACK_2F0'), (0x308, 'GAME_STRATEGY_CALLBACK_308')]:
        slot(strategy, offset, rvas[key])
    callbacks = validate_callbacks(image, rvas)
    callback_guards = [{'name': name, 'rva': rvas[name], 'hex': image.data[image.offset(rvas[name]):image.offset(rvas[name]) + 32].hex()}
                       for name in ('GAME_STRATEGY_CALLBACK_2E8', 'GAME_STRATEGY_CALLBACK_2F0', 'GAME_STRATEGY_CALLBACK_308')]
    ordinary = guards[:9]
    discovery_guards = guards[9:] + callbacks + callback_guards
    return {'schema_version': 1, 'mode': 'static_PE_only_no_process_access', 'profile_id': PROFILE_181['id'],
            'runtime_live_allowed': True,
            'images': {key: {'path': str(bin_path / name), 'sha256': hashes[key]}
                       for key, name in [('game', 'gamedll_ph_x64_rwdi.dll'), ('engine', 'engine_x64_rwdi.dll')]},
            'game_global_rva': '0x3b04c70', 'guarded_prologues': ordinary, 'discovery_prologues': discovery_guards,
            'vtables': {key: table_proof(image, table) for key, table in tables.items()},
            'dropped_proxy_static': {**table_proof(image, dropped_proxy), 'target_slot': '0x128',
                                     'target_rva': rvas['GAME_PROXY_TARGET_THUNK']},
            'disassembly': {hex(rva): image.disasm(rva, size) for rva, size in [(0xddd120, 31), (0xb3ecb0, 8), (0x12d96ef, 120), (0x1f09100, 196)]},
            'native_controller_vector': {'player_host_offset': '0x200', 'host_registry_offset': '0x1c8',
                                         'registry_list_offset': '0x1d8', 'registry_count_offset': '0x1e0',
                                         'pointer_mask': '0xffffffffffff', 'max_count': 256},
            'chain': {'game_level_offset': '0x138', 'level_client_offset': '0xec8', 'client_gate_offset': '0x88',
                      'client_player_offset': '0x90', 'trigger_owner_pointer_offset': '0x8',
                      'trigger_owner_vtable_slot_offset': '0x4a8', 'trigger_owner_getter_rva': '0x180440'},
            'limits': ['Découverte en lecture seule; les interactions du runtime restent soumises à leurs gardes propres.',
                       'La découverte locale ne qualifie ni les champs de butin, ni leur durée de vie, ni le crédit d’inventaire.']}
