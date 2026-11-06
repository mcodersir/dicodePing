import copy,importlib.util,pathlib,unittest,json
spec=importlib.util.spec_from_file_location('cache_key',pathlib.Path(__file__).with_name('android-native-cache-key.py'));cache=importlib.util.module_from_spec(spec);spec.loader.exec_module(cache)
class CacheKeyTests(unittest.TestCase):
    def setUp(self):self.value=cache.inputs()
    def test_existing_payloads_only_reused_for_identical_native_inputs(self):self.assertEqual(cache.cache_key(self.value),cache.LEGACY_CACHE_KEY if cache.digest(self.value)==cache.LEGACY_INPUT_DIGEST else 'Linux-dicode-native-v2-'+cache.digest(self.value))
    def test_android_core_change_invalidates(self):
        other=copy.deepcopy(self.value);other['pins']['android_build']['xray_commit']='different';self.assertNotEqual(cache.cache_key(other),cache.cache_key(self.value))
    def test_original_fox_source_change_invalidates(self):
        other=copy.deepcopy(self.value);name=next(n for n in other['files'] if n.endswith('provider.go'));other['files'][name]='changed';self.assertNotEqual(cache.cache_key(other),cache.cache_key(self.value))
    def test_native_recipe_or_toolchain_change_invalidates(self):
        for field in ['native_steps','toolchains']:
            other=copy.deepcopy(self.value);other['recipes'][cache.WORKFLOWS[0]][field]='changed';self.assertNotEqual(cache.cache_key(other),cache.cache_key(self.value))
    def test_desktop_mihomo_edits_do_not_change_native_inputs(self):
        def read(name):
            raw=(cache.ROOT/name).read_bytes()
            if name==cache.PIN_FILE:
                pins=json.loads(raw);pins['mihomo_version']='alpha-future';pins['mihomo_assets']={'changed':'desktop only'};return json.dumps(pins).encode()
            return raw.replace(b'mihomo-',b'future-mihomo-') if name in cache.WORKFLOWS else raw
        self.assertEqual(cache.inputs(read),self.value)
if __name__=='__main__':unittest.main()
