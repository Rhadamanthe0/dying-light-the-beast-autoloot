"""Les versions inconnues et les profils incomplets doivent rester refusés."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import runtime_profile
from runtime_profile import PROFILE_171, PROFILE_181, select_profile, compiled_core, fixture_image_size, profile_digest, profile_by_name, require_live_profile, make_trial_181


class RuntimeProfileTests(unittest.TestCase):
    def test_resident_modes_require_canonical_profile_and_hash_pair(self):
        for profile in (PROFILE_171,PROFILE_181):
            require_live_profile(profile,execution_mode='resident')
            for mode in (None,'trial-181','dummy','unknown'):
                with self.subTest(profile=profile['id'],mode=mode),self.assertRaises(ValueError):
                    require_live_profile(profile,execution_mode=mode)
            changed=copy.deepcopy(profile);changed['hashes']['engine']='unknown'
            with self.assertRaises(ValueError):
                require_live_profile(changed,execution_mode='resident')
    def test_trial_dispatch_cap_is_serialized_and_bounded(self):
        for category in ('corpses','ground','dropped','containers'):
            for cap in (1,32,64):
                trial=make_trial_181(PROFILE_181,15,category=category,dispatch_cap=cap)
                self.assertEqual(trial['dispatch_cap'],cap)
                require_live_profile(PROFILE_181,trial,'trial-181')
            for cap in (0,65,-1,True,1.5):
                with self.subTest(category=category,cap=cap),self.assertRaises(ValueError):
                    make_trial_181(PROFILE_181,15,category=category,dispatch_cap=cap)
        trial=make_trial_181(PROFILE_181,15,True,dispatch_cap=0)
        require_live_profile(PROFILE_181,trial,'trial-181')
        for cap in (1,32,64):
            with self.subTest(diagnostic_cap=cap),self.assertRaises(ValueError):
                make_trial_181(PROFILE_181,15,True,dispatch_cap=cap)
    def test_dropped_proxy_retains_171_type_and_has_exact_separate_181_type(self):
        self.assertEqual(PROFILE_171['rvas']['GAME_MODEL_PROXY_PRIMARY'], PROFILE_171['rvas']['GAME_PROXY_PRIMARY'])
        self.assertEqual(PROFILE_181['rvas']['GAME_MODEL_PROXY_PRIMARY'], 0x2d5cc10)
        self.assertNotEqual(PROFILE_181['rvas']['GAME_MODEL_PROXY_PRIMARY'], PROFILE_181['rvas']['GAME_PROXY_PRIMARY'])

    def test_trial_contract_requires_181_and_bounded_positive_milliseconds(self):
        for diagnostic in (False, True):
            for duration, expected_ms in [(0.001, 1), (0.0019, 1), (15, 15000), (30, 30000)]:
                trial = make_trial_181(PROFILE_181, duration, diagnostic, dispatch_cap=0 if diagnostic else 1)
                self.assertEqual(trial['duration_ms'], expected_ms)
                self.assertEqual(trial['mode'], 'diagnostic-only' if diagnostic else 'collect')
                self.assertEqual(trial['category'], 'corpses')
                require_live_profile(PROFILE_181, trial, 'trial-181')
        for duration in (0, -1, 30.001, 0.0009, float('nan'), float('inf'), -float('inf'), True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                make_trial_181(PROFILE_181, duration)
        with self.assertRaises(ValueError):
            make_trial_181(PROFILE_171, 15)
        changed = copy.deepcopy(PROFILE_181)
        changed['hashes']['engine'] = PROFILE_171['hashes']['engine']
        with self.assertRaises(ValueError):
            make_trial_181(changed, 15)

    def test_trial_contract_mutations_cannot_authorize_activation(self):
        trial = make_trial_181(PROFILE_181, 15)
        for key, value in [('kind', 'other'), ('profile_id', PROFILE_171['id']), ('hashes', PROFILE_171['hashes']),
                           ('mode', 'all'), ('category', 'unknown'), ('category', ['ground']),
                           ('duration_ms', 0), ('duration_ms', 30001), ('duration_ms', 1.5), ('duration_ms', True),
                           ('dispatch_cap', 0), ('dispatch_cap', 65), ('dispatch_cap', 1.5), ('dispatch_cap', True)]:
            changed = copy.deepcopy(trial)
            changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                require_live_profile(PROFILE_181, changed, 'trial-181')
        changed = {**trial, 'unreviewed': True}
        with self.assertRaises(ValueError):
            require_live_profile(PROFILE_181, changed, 'trial-181')
        with self.assertRaises(ValueError):
            require_live_profile(PROFILE_171, trial, 'trial-181')

    def test_trial_categories_are_explicit_and_diagnosis_remains_corpses_only(self):
        for category in ('corpses', 'ground', 'dropped', 'containers'):
            trial = make_trial_181(PROFILE_181, 15, category=category)
            self.assertEqual(trial['category'], category)
            self.assertEqual(trial['mode'], 'collect')
            require_live_profile(PROFILE_181, trial, 'trial-181')
            if category != 'corpses':
                with self.subTest(category=category), self.assertRaises(ValueError):
                    make_trial_181(PROFILE_181, 15, True, category)
                trial['mode'] = 'diagnostic-only'
                with self.assertRaises(ValueError):
                    require_live_profile(PROFILE_181, trial, 'trial-181')
        for category in ('unknown', '', None, ['ground']):
            with self.subTest(category=category), self.assertRaises(ValueError):
                make_trial_181(PROFILE_181, 15, category=category)
        trial = make_trial_181(PROFILE_181, 15)
        del trial['category']
        with self.assertRaises(ValueError):
            require_live_profile(PROFILE_181, trial, 'trial-181')

    def test_181_has_its_own_fixture_and_explicit_normal_mode(self):
        profile = profile_by_name('1.8.1')
        self.assertEqual(profile['id'], '1.8.1.0na')
        self.assertFalse(profile['experimental'])
        self.assertGreater(fixture_image_size(profile), fixture_image_size(PROFILE_171))
        self.assertNotEqual(compiled_core('int x=RVA_GAME_BODY_PRIMARY;', profile),
                            compiled_core('int x=RVA_GAME_BODY_PRIMARY;', PROFILE_171))
        require_live_profile(profile, execution_mode='resident')
        with self.assertRaises(ValueError):
            require_live_profile(profile)
        require_live_profile(PROFILE_171, execution_mode='resident')

    def test_incomplete_181_never_reuses_legacy_addresses(self):
        profile = copy.deepcopy(PROFILE_181)
        del profile['rvas']['GAME_PLAYER_PRIMARY']
        with patch.object(runtime_profile, 'PROFILE_181', profile), self.assertRaisesRegex(ValueError, 'incomplete'):
            select_profile(profile['hashes']['game'], profile['hashes']['engine'])

    def test_selection_requires_both_exact_hashes(self):
        hashes = PROFILE_171['hashes']
        for game, engine in [('unknown', hashes['engine']), (hashes['game'], 'unknown'),
                             ('unknown', 'unknown'), (hashes['engine'], hashes['game'])]:
            with self.subTest(game=game, engine=engine), self.assertRaises(ValueError):
                select_profile(game, engine)
        selected = select_profile(hashes['game'], hashes['engine'])
        selected['rvas']['GAME_PLAYER_PRIMARY'] = 1
        self.assertNotEqual(selected['rvas'], PROFILE_171['rvas'])

    def test_compilation_refuses_missing_unknown_and_invalid_addresses(self):
        source = 'int address = RVA_GAME_PLAYER_PRIMARY;'
        for mutation in ('missing', 'unknown', 'invalid'):
            profile = copy.deepcopy(PROFILE_171)
            if mutation == 'missing':
                del profile['rvas']['GAME_PLAYER_PRIMARY']
            elif mutation == 'unknown':
                profile['rvas']['UNREVIEWED'] = 0x1234
            else:
                profile['rvas']['GAME_PLAYER_PRIMARY'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                compiled_core(source, profile)
        with self.assertRaises(ValueError):
            compiled_core('int address = RVA_UNREVIEWED;')

    def test_profile_changes_change_the_actual_compiled_source(self):
        source = 'int address = RVA_GAME_PLAYER_PRIMARY;'
        changed = copy.deepcopy(PROFILE_171)
        changed['rvas']['GAME_PLAYER_PRIMARY'] += 8
        self.assertNotEqual(compiled_core(source), compiled_core(source, changed))
        self.assertNotEqual(profile_digest(PROFILE_171), profile_digest(changed))
        self.assertGreater(fixture_image_size(changed), max(changed['rvas'].values()) + 0x12a8)


@unittest.skipUnless(shutil.which('node'), 'Node requis pour exécuter le vrai JavaScript avec frontières simulées')
class TrialJavascriptTests(unittest.TestCase):
    def test_normal_profiles_refuse_unknown_modes_and_mixed_hashes_before_hook(self):
        cases=[]
        for profile in (PROFILE_171,PROFILE_181):
            base=self.config();base.update(profile_id=profile['id'],profile_hashes=profile['hashes'],
                game_sha256=profile['hashes']['game'],engine_module={'sha256':profile['hashes']['engine']},
                execution_mode='resident',trial_181=None,rvas=profile['rvas'])
            for path,value in [(['profile_id'],'unknown'),(['execution_mode'],'trial-181'),
                (['execution_mode'],'dummy'),(['profile_hashes','game'],'bad'),
                (['profile_hashes','engine'],'bad'),(['game_sha256'],'bad'),(['engine_module','sha256'],'bad')]:
                config=copy.deepcopy(base);target=config
                for key in path[:-1]:target=target[key]
                target[path[-1]]=value
                cases.append({'name':str((profile['id'],path)),'config':config,'guard':'Reviewed profile'})
        for result in self.execute(cases):
            self.assertEqual(result['identity'],0,result['name'])
            self.assertEqual(result['attached'],0,result['name'])
            self.assertIn('Reviewed profile',str(result['messages'][-1]['errors']))

    def config(self, diagnostic=False, category='corpses', dispatch_cap=None):
        dispatch_cap=(0 if diagnostic else 1) if dispatch_cap is None else dispatch_cap
        trial = make_trial_181(PROFILE_181, 15, diagnostic, category, dispatch_cap)
        categories = {'corpses': ['0', '1', '1', '0', '0'], 'ground': ['1', '1', '0', '0', '0'],
                      'dropped': ['0', '1', '0', '0', '1'], 'containers': ['0', '1', '0', '1', '0']}
        routes = ['0', '0', '0', '0', '0'] if diagnostic else categories[category]
        routes[1]=str(dispatch_cap)
        return {'profile_id': PROFILE_181['id'], 'profile_hashes': dict(PROFILE_181['hashes']),
                'game_sha256': PROFILE_181['hashes']['game'], 'engine_module': {'sha256': PROFILE_181['hashes']['engine']},
                'execution_mode': 'trial-181', 'trial_181': trial, 'rvas': PROFILE_181['rvas'],
                'pid': 42, 'duration_ms': 15000, 'interval_ms': 100, 'radius_metres': 2,
                'phase': 'player-update', 'values': ['0'] * 11 + routes}

    def execute(self, cases):
        source = (Path(__file__).resolve().parents[1] / 'tools/autoloot_runtime.js').read_text(encoding='utf-8')
        runner = r'''
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),results=[];
for(const row of input.cases){
  let identity=0,attached=0;const messages=[];
  const sandbox={Frida:{version:'17.24.0'},Script:{runtime:'QJS'},rpc:{exports:{}},
    Process:{arch:'x64',platform:'windows',pointerSize:8,id:42,getModuleByName(){identity++;throw Error('IDENTITY_BOUNDARY');}},
    Interceptor:{attach(){attached++;throw Error('UNEXPECTED_HOOK');},flush(){}},send(value){messages.push(value);}};
  const code=input.source.replace('__QUERY_CONFIG__',JSON.stringify(row.config)).replace('__QUERY_CORE__',"''");
  vm.runInNewContext(code,sandbox,{timeout:1000});
  results.push({name:row.name,guard:row.guard||'Trial181',identity,attached,messages});
}
process.stdout.write(JSON.stringify(results));
'''
        result = subprocess.run([shutil.which('node'), '-e', runner],
                                input=json.dumps({'source': source, 'cases': cases}),
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_actual_javascript_refuses_each_trial_mutation_before_identity_and_hook(self):
        cases = []
        categories = ('corpses', 'ground', 'dropped', 'containers')
        for diagnostic, category in [(False, value) for value in categories] + [(True, 'corpses')]:
            base = self.config(diagnostic, category)
            changes = [(['execution_mode'], 'resident'), (['profile_id'], PROFILE_171['id']),
                       (['trial_181'], None), (['trial_181'], []), (['trial_181', 'kind'], 'other'),
                       (['trial_181', 'profile_id'], PROFILE_171['id']), (['trial_181', 'mode'], 'all'),
                       (['trial_181', 'dispatch_cap'], 32 if not diagnostic else 1),
                       (['trial_181', 'mode'], 'collect' if diagnostic else 'diagnostic-only'),
                       (['trial_181', 'category'], 'unknown'), (['trial_181', 'category'], ['ground']),
                       (['trial_181', 'category'], categories[(categories.index(category) + 1) % 4]),
                       (['trial_181', 'hashes', 'game'], 'bad'), (['trial_181', 'hashes', 'engine'], 'bad'),
                       (['profile_hashes', 'game'], 'bad'), (['profile_hashes', 'engine'], 'bad'),
                       (['game_sha256'], 'bad'), (['engine_module', 'sha256'], 'bad'),
                       (['duration_ms'], 14999), (['trial_181', 'duration_ms'], 14999),
                       (['values'], base['values'][:-1])]
            for index in range(11, 16):
                changes.append((['values', index], '1' if base['values'][index] == '0' else '0'))
            changes.append((['values', 12], 0 if diagnostic else 1))
            for path, value in changes:
                config = copy.deepcopy(base)
                target = config
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                cases.append({'name': str((diagnostic, category, path, value)), 'config': config,
                              'guard':'Reviewed profile' if path==['trial_181'] and value is None else 'Trial181'})
            config = copy.deepcopy(base)
            config['values'][12] = '2'
            cases.append({'name': str((diagnostic, category, 'cap2')), 'config': config})
            config = copy.deepcopy(base)
            del config['trial_181']['category']
            cases.append({'name': str((diagnostic, category, 'missing-category')), 'config': config})
            for duration in (0, -1, 30001, 1.5, True):
                config = copy.deepcopy(base)
                config['duration_ms'] = config['trial_181']['duration_ms'] = duration
                cases.append({'name': str((diagnostic, category, 'duration', duration)), 'config': config,
                              'guard': 'Reviewed runtime' if duration < 0 else 'Trial181'})
            config = copy.deepcopy(base)
            config['trial_181']['extra'] = True
            cases.append({'name': str((diagnostic, category, 'extra')), 'config': config})
            config = copy.deepcopy(base)
            config.update(profile_id=PROFILE_171['id'], execution_mode='resident', trial_181=None)
            cases.append({'name': str((diagnostic, category, 'mislabeled-181')), 'config': config, 'guard':'Reviewed profile'})
        for category in ('ground', 'dropped', 'containers'):
            config = self.config(True)
            config['trial_181']['category'] = category
            cases.append({'name': 'diagnostic-category-' + category, 'config': config})
        for diagnostic in (False,True):
            for cap in ((0,65,-1,True,1.5) if not diagnostic else (1,32,64)):
                config=self.config(diagnostic)
                config['trial_181']['dispatch_cap']=cap
                config['values'][12]=str(cap)
                cases.append({'name':str(('invalid-cap',diagnostic,cap)),'config':config})
        for result in self.execute(cases):
            with self.subTest(case=result['name']):
                self.assertEqual(result['identity'], 0)
                self.assertEqual(result['attached'], 0)
                self.assertIn(result['guard'], str(result['messages'][-1]['errors']))

    def test_valid_contracts_and_normal_171_reach_the_identity_boundary(self):
        cases = [{'name': category+'-cap'+str(cap), 'config': self.config(category=category, dispatch_cap=cap)}
                 for category in ('corpses', 'ground', 'dropped', 'containers') for cap in (1,32,64)]
        cases.append({'name': 'diagnostic', 'config': self.config(True)})
        normal=self.config();normal.update(execution_mode='resident',trial_181=None)
        cases.append({'name':'normal181','config':normal})
        legacy = self.config()
        legacy.update(profile_id=PROFILE_171['id'], execution_mode='resident', trial_181=None,
                      profile_hashes=PROFILE_171['hashes'], game_sha256=PROFILE_171['hashes']['game'],
                      engine_module={'sha256': PROFILE_171['hashes']['engine']}, rvas=PROFILE_171['rvas'])
        cases.append({'name': 'legacy', 'config': legacy})
        # Le premier contrôle d'identité devient un arrêt observé; aucun hook n'est installé dans ces tests.
        for result in self.execute(cases):
            with self.subTest(case=result['name']):
                self.assertEqual(result['identity'], 1)
                self.assertEqual(result['attached'], 0)
                self.assertIn('IDENTITY_BOUNDARY', str(result['messages'][-1]['errors']))


if __name__ == '__main__':
    unittest.main()
