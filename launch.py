"""Start both interfaces independently of background model downloads."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import threading
import urllib.request


def settings():
    workspace = Path(os.environ.get('WORKSPACE', '/workspace'))
    return {
        'workspace': workspace,
        'comfy': Path(os.environ.get('COMFYUI_DIR', str(workspace / 'ComfyUI'))),
        'seed': Path(os.environ.get('COMFYUI_SEED', '/opt/comfyui-seed')),
        'template': Path(os.environ.get('TEMPLATE_HOME', '/opt/template')),
        'python': os.environ.get('COMFYUI_PYTHON', '/opt/venv/bin/python'),
        'jupyter': os.environ.get('JUPYTER_BIN', '/opt/jupyter/bin/jupyter'),
    }


def log(message):
    print(f'[Startup] {message}', flush=True)


def state(cfg, stage, message, *, filename='startup-status.json'):
    path = cfg['workspace'] / 'logs' / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'stage': stage, 'message': message}, indent=2) + '\n')
    os.replace(temporary, path)
    log(message)


def prepare(cfg):
    state(cfg, 'prepare', 'Preparing ComfyUI; model downloads will not delay the interface.')
    comfy, seed = cfg['comfy'], cfg['seed']
    if not comfy.exists():
        temporary = cfg['workspace'] / '.comfyui-seed'
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(seed, temporary)
        temporary.rename(comfy)
    expected = (seed / '.image-comfyui-commit').read_text().strip()
    marker = comfy / '.image-comfyui-commit'
    if not (comfy / 'main.py').is_file() or not marker.is_file() or marker.read_text().strip() != expected:
        raise ValueError('Existing ComfyUI directory does not match this image release; preserve your data and migrate to a matching installation.')
    head = subprocess.check_output(['git', '-C', str(comfy), 'rev-parse', 'HEAD'], text=True).strip()
    if head != expected:
        raise ValueError('ComfyUI code was updated separately from its image dependencies; use a matching image.')
    for folder in ('diffusion_models', 'loras', 'vae', 'text_encoders'):
        (comfy / 'models' / folder).mkdir(parents=True, exist_ok=True)
    state(cfg, 'workflows', 'Installing bundled workflows without replacing existing files.')
    subprocess.run([cfg['python'], str(cfg['template'] / 'install_workflows.py'),
                    '--source', str(cfg['template'] / 'workflows'),
                    '--destination', str(comfy / 'user/default/workflows')], check=True)


def engine_command(cfg, arguments):
    return [cfg['python'], str(cfg['comfy'] / 'main.py'), '--listen', '0.0.0.0',
            '--port', '8188', '--enable-manager', *arguments]


def run_models(cfg):
    manifest = os.environ.get('MODEL_MANIFEST') or str(cfg['template'] / 'models.json')
    if os.environ.get('ENABLE_MODEL_DOWNLOADS', '1') == '0':
        state(cfg, 'disabled', 'Automatic model downloads are disabled.', filename='model-status.json')
        return 0
    state(cfg, 'downloading', f'Checking/downloading models from {manifest}; both interfaces start independently.', filename='model-status.json')
    try:
        result = subprocess.run([cfg['python'], str(cfg['template'] / 'download_models.py'),
                                 '--manifest', manifest, '--comfyui', str(cfg['comfy'])])
        if result.returncode:
            raise RuntimeError(f'downloader exited with status {result.returncode}')
    except Exception as exc:
        state(cfg, 'failed', f'Model downloads failed ({type(exc).__name__}). ComfyUI stays open. See logs/models.log, correct the manifest/access or disk issue, then restart to retry.', filename='model-status.json')
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    state(cfg, 'ready', 'Configured models are ready. Refresh ComfyUI model definitions or reload the workflow to update model choices.', filename='model-status.json')
    return 0


def jupyter_command(cfg):
    origin = os.environ.get('JUPYTER_ALLOW_ORIGIN', '')
    if not origin and os.environ.get('RUNPOD_POD_ID'):
        origin = f"https://{os.environ['RUNPOD_POD_ID']}-8888.proxy.runpod.net"
    command = [cfg['jupyter'], 'lab', '--allow-root', '--no-browser', '--ip=0.0.0.0',
               '--port=8888', '--ServerApp.port_retries=0',
               f"--ServerApp.root_dir={cfg['workspace']}",
               '--ServerApp.allow_remote_access=True', '--ServerApp.trust_xheaders=True',
               '--ServerApp.terminals_enabled=True',
               '--ServerApp.terminado_settings={"shell_command":["/bin/bash"]}',
               f"--IdentityProvider.token={os.environ.get('JUPYTER_TOKEN', '')}",
               '--PasswordIdentityProvider.hashed_password=']
    if origin:
        command.append(f'--ServerApp.allow_origin={origin}')
    return command


def terminate(processes):
    # A group may still contain a downloader/kernel after its original leader exits.
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                raise
    deadline = time.monotonic() + 5
    for process in processes:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                raise
        process.wait()


def mirror(stream, output, prefix):
    for line in iter(stream.readline, b''):
        output.write(line)
        print(f'[{prefix}] {line.decode("utf-8", "replace").rstrip()}', flush=True)
    stream.close()


def start_logged(command, output, prefix, threads, **kwargs):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, **kwargs)
    thread = threading.Thread(target=mirror, args=(process.stdout, output, prefix), daemon=True)
    thread.start()
    threads.append(thread)
    return process


def ready():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def supervise(cfg, arguments):
    cfg['workspace'].mkdir(parents=True, exist_ok=True)
    logs = cfg['workspace'] / 'logs'
    logs.mkdir(exist_ok=True)
    os.environ.setdefault('HF_HOME', str(cfg['workspace'] / '.cache/huggingface'))
    os.environ.setdefault('XDG_CONFIG_HOME', str(cfg['workspace'] / '.config'))
    for name in ('HF_HOME', 'XDG_CONFIG_HOME'):
        Path(os.environ[name]).mkdir(parents=True, exist_ok=True)
    processes, files, threads = [], [], []
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        jupyter = None
        if os.environ.get('ENABLE_JUPYTER', '1') == '1':
            output = (logs / 'jupyter.log').open('ab', buffering=0)
            files.append(output)
            environment = os.environ.copy()
            environment['JUPYTER_PREFER_ENV_PATH'] = '1'
            # Limit accidental inheritance; this does not isolate a root terminal.
            environment.pop('HF_TOKEN', None)
            jupyter = subprocess.Popen(jupyter_command(cfg), cwd=cfg['workspace'], env=environment,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(jupyter)
            log('Jupyter starting on port 8888; log: /workspace/logs/jupyter.log')
        output = (logs / 'comfyui.log').open('ab', buffering=0)
        files.append(output)
        engine = None
        try:
            prepare(cfg)
            state(cfg, 'launching', 'Launching ComfyUI on 8188 with Manager enabled; models download separately.')
            engine = start_logged(engine_command(cfg, arguments), output, 'ComfyUI', threads, cwd=cfg['comfy'])
            processes.append(engine)
            model_output = (logs / 'models.log').open('ab', buffering=0)
            files.append(model_output)
            downloader = start_logged([cfg['python'], str(Path(__file__).resolve()), '--models'],
                                      model_output, 'Models', threads)
            processes.append(downloader)
            log('Model progress: /workspace/logs/models.log and model-status.json. Do not queue workflows until their required models are ready.')
        except Exception as exc:
            output.write((str(exc) + '\n').encode())
            state(cfg, 'failed', f'ComfyUI preparation failed ({type(exc).__name__}): {exc}. Jupyter stays available when enabled.')
            if jupyter is None:
                return 1
        reported = False
        readiness_reported = False
        started = time.monotonic()
        next_readiness = started
        slow_reported = False
        while not stopping:
            if jupyter is not None and jupyter.poll() is not None:
                log(f'Jupyter exited with status {jupyter.returncode}; inspect logs/jupyter.log. ComfyUI continues independently.')
                jupyter = None
            if engine is None and jupyter is None:
                return 1
            if engine is not None:
                now = time.monotonic()
                if not readiness_reported and now >= next_readiness:
                    next_readiness = now + 2
                    if ready():
                        state(cfg, 'ready', 'ComfyUI is reachable on port 8188. Model downloads run independently; check model-status.json before queueing workflows.')
                        readiness_reported = True
                    elif now - started > 120 and not slow_reported:
                        log('ComfyUI has not responded on 8188 after 120 seconds. This is NOT a model-download wait; inspect the ComfyUI messages in this container log or logs/comfyui.log.')
                        slow_reported = True
                code = engine.poll()
                if code is not None:
                    if jupyter is None:
                        return code
                    if not reported:
                        state(cfg, 'stopped' if code == 0 else 'failed',
                              f'ComfyUI exited with status {code}. Jupyter stays available; inspect logs/comfyui.log.')
                        reported = True
            time.sleep(0.25)
        return 0
    except OSError as exc:
        log(f'Could not start a service: {exc}')
        return 1
    finally:
        terminate(processes)
        for thread in threads:
            thread.join(timeout=3)
        for file in files:
            file.close()


if __name__ == '__main__':
    cfg = settings()
    if sys.argv[1:2] == ['--models']:
        sys.exit(run_models(cfg))
    sys.exit(supervise(cfg, sys.argv[1:]))
