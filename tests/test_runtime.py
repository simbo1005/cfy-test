"""Offline regressions for startup recovery, proxy configuration and model parsing."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


launch = module('launch', 'launch.py')
models = module('models', 'download_models.py')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_dataset_and_model_links(self):
        manifest = self.root / 'models.json'
        manifest.write_text(json.dumps({
            'diffusion_models': ['https://huggingface.co/datasets/example/assets/resolve/main/sub/model.safetensors'],
            'loras': ['https://huggingface.co/example/assets/blob/main/lora.safetensors'],
            'vae': [], 'text_encoders': [],
        }))
        parsed = models.read_models(manifest, self.root / 'ComfyUI')
        self.assertEqual(parsed[0]['repo_type'], 'dataset')
        self.assertEqual(parsed[0]['repo_id'], 'example/assets')
        self.assertEqual(parsed[0]['remote'], 'sub/model.safetensors')
        self.assertEqual(parsed[1]['repo_type'], 'model')
        calls = []
        def fake(**kwargs):
            calls.append(kwargs)
            target = Path(kwargs['local_dir']) / kwargs['filename']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'weights')
            return str(target)
        models.download_all(manifest, self.root / 'ComfyUI', download=fake)
        models.download_all(manifest, self.root / 'ComfyUI', download=fake)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['repo_type'], 'dataset')

    def test_json_error_names_file_and_location(self):
        manifest = self.root / 'broken.json'
        manifest.write_text('{\n "loras": [\n URL\n ]}')
        with self.assertRaisesRegex(ValueError, 'broken.json: invalid JSON at line 3, column 2'):
            models.read_models(manifest, self.root)

    def test_rejects_duplicate_destination_and_parent_path(self):
        manifest = self.root / 'models.json'
        manifest.write_text(json.dumps({'loras': [
            'https://huggingface.co/example/assets/resolve/main/a/model.safetensors',
            'https://huggingface.co/example/assets/resolve/main/b/model.safetensors']}))
        with self.assertRaisesRegex(ValueError, 'Duplicate destination'):
            models.read_models(manifest, self.root)
        manifest.write_text(json.dumps({'vae': [{
            'url': 'https://huggingface.co/example/assets/resolve/main/model.safetensors',
            'filename': '../escape.safetensors'}]}))
        with self.assertRaisesRegex(ValueError, 'plain filename'):
            models.read_models(manifest, self.root)

    def test_runpod_origin_and_correct_auth_option(self):
        old = os.environ.copy()
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.pop('JUPYTER_ALLOW_ORIGIN', None)
        os.environ.pop('JUPYTER_TOKEN', None)
        os.environ['RUNPOD_POD_ID'] = 'examplepod'
        command = launch.jupyter_command(launch.settings())
        self.assertIn('--ServerApp.allow_origin=https://examplepod-8888.proxy.runpod.net', command)
        self.assertIn('--ServerApp.terminals_enabled=True', command)
        self.assertIn('--PasswordIdentityProvider.hashed_password=', command)
        self.assertNotIn('--PasswordIdentityProvider.hashed_passwords=', command)
        self.assertIn('--IdentityProvider.token=', command)

    def fixture(self, valid=True, jupyter=True, slow_downloads=False, jupyter_fails=False, mismatch=False):
        seed = self.root / 'seed'
        seed.mkdir()
        (seed / 'main.py').write_text('import time\nprint("ENGINE_READY", flush=True)\nwhile True: time.sleep(1)\n')
        subprocess.run(['git', 'init', '-q', str(seed)], check=True)
        subprocess.run(['git', '-C', str(seed), 'add', 'main.py'], check=True)
        subprocess.run(['git', '-C', str(seed), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '-qm', 'seed'], check=True)
        head = subprocess.check_output(['git', '-C', str(seed), 'rev-parse', 'HEAD'], text=True).strip()
        (seed / '.image-comfyui-commit').write_text(head)
        fake = self.root / 'jupyter'
        fake.write_text(f'#!{sys.executable}\nimport time,os\nfrom pathlib import Path\nPath(os.environ["WORKSPACE"],"jupyter.pid").write_text(str(os.getpid()))\nwhile True: time.sleep(1)\n')
        if jupyter_fails:
            fake.write_text(f'#!{sys.executable}\nraise SystemExit(2)\n')
        fake.chmod(0o755)
        manifest = self.root / 'models.json'
        manifest.write_text('{"diffusion_models": [], "loras": []}' if valid else '{"loras": [BAD]}')
        workspace = self.root / 'workspace'
        if mismatch:
            (workspace / 'ComfyUI').mkdir(parents=True)
            (workspace / 'ComfyUI/main.py').write_text('existing user code')
        template = ROOT
        if slow_downloads:
            template = self.root / 'template'
            template.mkdir()
            (template / 'install_workflows.py').write_text((ROOT / 'install_workflows.py').read_text())
            (template / 'workflows').mkdir()
            (template / 'download_models.py').write_text('import time\nprint("SLOW_DOWNLOAD_RUNNING", flush=True)\ntime.sleep(30)\n')
        env = dict(os.environ, WORKSPACE=str(workspace), COMFYUI_DIR=str(workspace / 'ComfyUI'),
                   COMFYUI_SEED=str(seed), TEMPLATE_HOME=str(template), COMFYUI_PYTHON=sys.executable,
                   JUPYTER_BIN=str(fake), MODEL_MANIFEST=str(manifest), ENABLE_JUPYTER='1' if jupyter else '0')
        env.pop('XDG_CONFIG_HOME', None)
        env.pop('HF_HOME', None)
        output = (self.root / 'supervisor.log').open('w')
        self.addCleanup(output.close)
        process = subprocess.Popen([sys.executable, str(ROOT / 'launch.py')], env=env, stdout=output, stderr=output)
        def cleanup():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=12)
        self.addCleanup(cleanup)
        return process, workspace

    def wait_for(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        self.fail('Timed out waiting for startup state')

    def test_bad_manifest_preserves_both_services_and_cleans_up_on_stop(self):
        process, workspace = self.fixture(valid=False)
        status = workspace / 'logs/model-status.json'
        def failed():
            try:
                return json.loads(status.read_text())['stage'] == 'failed'
            except (OSError, json.JSONDecodeError):
                return False
        self.wait_for(failed)
        output = workspace / 'logs/comfyui.log'
        self.wait_for(lambda: output.exists() and 'ENGINE_READY' in output.read_text())
        self.assertIsNone(process.poll())
        self.wait_for(lambda: (workspace / 'jupyter.pid').exists())
        pid = int((workspace / 'jupyter.pid').read_text())
        os.kill(pid, 0)
        self.assertIn('invalid JSON at line', (workspace / 'logs/models.log').read_text())
        process.terminate()
        self.assertEqual(process.wait(timeout=12), 0, (self.root / 'supervisor.log').read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_long_download_does_not_block_engine(self):
        process, workspace = self.fixture(valid=True, slow_downloads=True)
        output = workspace / 'logs/comfyui.log'
        download_log = workspace / 'logs/models.log'
        self.wait_for(lambda: output.exists() and 'ENGINE_READY' in output.read_text())
        self.wait_for(lambda: download_log.exists() and 'SLOW_DOWNLOAD_RUNNING' in download_log.read_text())
        self.assertEqual(json.loads((workspace / 'logs/model-status.json').read_text())['stage'], 'downloading')
        self.wait_for(lambda: 'SLOW_DOWNLOAD_RUNNING' in (self.root / 'supervisor.log').read_text())
        self.wait_for(lambda: 'ENGINE_READY' in (self.root / 'supervisor.log').read_text())
        self.assertIsNone(process.poll())

    def test_jupyter_failure_does_not_stop_comfyui(self):
        process, workspace = self.fixture(jupyter_fails=True)
        output = workspace / 'logs/comfyui.log'
        self.wait_for(lambda: output.exists() and 'ENGINE_READY' in output.read_text())
        self.wait_for(lambda: 'ComfyUI continues independently' in (self.root / 'supervisor.log').read_text())
        self.assertIsNone(process.poll())

    def test_existing_mismatched_source_is_preserved_and_jupyter_stays_open(self):
        process, workspace = self.fixture(mismatch=True)
        status = workspace / 'logs/startup-status.json'
        def failed():
            try:
                return json.loads(status.read_text())['stage'] == 'failed'
            except (OSError, json.JSONDecodeError):
                return False
        self.wait_for(failed)
        self.assertIsNone(process.poll())
        self.assertEqual((workspace / 'ComfyUI/main.py').read_text(), 'existing user code')
        self.assertFalse((workspace / 'logs/model-status.json').exists())

    def test_valid_manifest_launches_engine(self):
        process, workspace = self.fixture(valid=True)
        output = workspace / 'logs/comfyui.log'
        self.wait_for(lambda: output.exists() and 'ENGINE_READY' in output.read_text())
        self.assertIsNone(process.poll())
        self.assertTrue((workspace / 'ComfyUI/.image-comfyui-commit').is_file())

    def test_failed_download_does_not_stop_engine_without_jupyter(self):
        process, workspace = self.fixture(valid=False, jupyter=False)
        output = workspace / 'logs/comfyui.log'
        status = workspace / 'logs/model-status.json'
        self.wait_for(lambda: output.exists() and 'ENGINE_READY' in output.read_text())
        def failed():
            try:
                return json.loads(status.read_text())['stage'] == 'failed'
            except (OSError, json.JSONDecodeError):
                return False
        self.wait_for(failed)
        self.assertIsNone(process.poll())


if __name__ == '__main__':
    unittest.main()
