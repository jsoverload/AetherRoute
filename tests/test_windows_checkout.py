"""Real Git checkouts exercise Windows-style line endings and packaged maps."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from package_release import members
from security import ValidationError
from world_maps import built_in_maps, load_built_in

ROOT=Path(__file__).resolve().parents[1]

class SourceReleaseTests(unittest.TestCase):
    def test_public_source_carries_the_checkout_rule_and_original_map_bytes(self):
        # Exercise generated release members, not the unfiltered working tree.
        data=members()
        self.assertIn('.gitattributes',data)
        self.assertIn('tests/test_windows_checkout.py',data)
        self.assertIn(b'maps/*.map.json text eol=lf',data['.gitattributes'])
        for entry in built_in_maps(ROOT):
            self.assertEqual(hashlib.sha256(data['maps/'+entry['file']]).hexdigest(),entry['sha256'])

@unittest.skipUnless(shutil.which('git'),'Git is needed for the Windows checkout regression.')
class WindowsCheckoutTests(unittest.TestCase):
    def test_both_worlds_survive_fresh_windows_style_checkout(self):
        with tempfile.TemporaryDirectory(prefix='aetherroute-checkout-') as directory:
            root=Path(directory);(root/'maps').mkdir()
            entries=built_in_maps(ROOT)
            # Source release inputs have the same bytes as the public Git blobs.
            for name in ['index.json']+[entry['file'] for entry in entries]:
                raw=(ROOT/'maps'/name).read_bytes().replace(b'\r\n',b'\n')
                (root/'maps'/name).write_bytes(raw)
            environment=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,
                             GIT_AUTHOR_NAME='AetherRoute checkout test',GIT_AUTHOR_EMAIL='test@example.invalid',
                             GIT_COMMITTER_NAME='AetherRoute checkout test',GIT_COMMITTER_EMAIL='test@example.invalid')
            def git(*args):
                result=subprocess.run(['git',*args],cwd=root,env=environment,stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,encoding='utf-8',errors='replace',timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                return result.stdout
            git('init','-q');git('config','core.autocrlf','false')
            git('add','maps');git('commit','-q','-m','Generated map fixture')
            git('config','core.autocrlf','true');git('config','core.eol','crlf')
            def fresh_checkout():
                for entry in entries:(root/'maps'/entry['file']).unlink()
                git('checkout-index','--all','--force')
            # Reproduce the failing Windows build with the old repository rules.
            fresh_checkout()
            for entry in entries:
                with self.subTest(stage='before',world=entry['name']):
                    raw=(root/'maps'/entry['file']).read_bytes()
                    self.assertIn(b'\r\n',raw)
                    self.assertNotEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
                    with self.assertRaisesRegex(ValidationError,'incomplete or modified'):load_built_in(root,entry)
            # A fresh checkout now preserves LF despite the Windows Git settings.
            (root/'.gitattributes').write_bytes((ROOT/'.gitattributes').read_bytes())
            git('add','.gitattributes');git('commit','-q','-m','Keep bundled map bytes stable')
            fresh_checkout()
            for entry in built_in_maps(root):
                with self.subTest(stage='after',world=entry['name']):
                    raw=(root/'maps'/entry['file']).read_bytes()
                    self.assertNotIn(b'\r\n',raw)
                    self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
                    pack,image=load_built_in(root,entry)
                    self.assertEqual(pack['world_id'],entry['world_id'])
                    self.assertEqual(image.size,(2048,2048))

if __name__=='__main__':unittest.main()
