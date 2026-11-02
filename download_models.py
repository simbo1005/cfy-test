"""Download configured Hugging Face files independently of ComfyUI startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
import threading
from urllib.parse import unquote, urlsplit

FOLDERS = ('diffusion_models', 'loras', 'vae', 'text_encoders')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_models(manifest, comfyui):
    try:
        config = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'{manifest}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}. Use double-quoted URLs, no comments, and no trailing commas.') from None
    if not isinstance(config, dict) or set(config) - set(FOLDERS):
        raise ValueError('Model manifest must contain only these lists: ' + ', '.join(FOLDERS))
    models, seen = [], set()
    for folder in FOLDERS:
        entries = config.get(folder, [])
        if not isinstance(entries, list):
            raise ValueError(f'{folder} must be a list')
        for entry in entries:
            entry = {'url': entry} if isinstance(entry, str) else entry
            if not isinstance(entry, dict) or set(entry) - {'url', 'filename', 'sha256'}:
                raise ValueError(f'{folder}: use a URL string or an object with url, filename, sha256')
            url = entry.get('url')
            if not isinstance(url, str):
                raise ValueError(f'{folder}: missing URL')
            u = urlsplit(url)
            parts = u.path.strip('/').split('/')
            repo_type = 'model'
            if parts and parts[0] == 'datasets':
                repo_type = 'dataset'
                parts = parts[1:]
            if (u.scheme != 'https' or u.netloc not in ('huggingface.co', 'www.huggingface.co')
                    or len(parts) < 5 or parts[2] not in ('resolve', 'blob')):
                raise ValueError(f'{folder}: use a Hugging Face file link, not a repository link')
            owner, repo, _, revision = [unquote(x) for x in parts[:4]]
            if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', x) or x in ('.', '..') for x in (owner, repo)):
                raise ValueError(f'{folder}: invalid repository name')
            remote = '/'.join(unquote(x) for x in parts[4:])
            remote_parts = remote.split('/')
            if not revision or any(x in ('', '.', '..') for x in remote_parts) or '\\' in remote:
                raise ValueError(f'{folder}: invalid file path')
            filename = entry.get('filename', PurePosixPath(remote).name)
            if (not isinstance(filename, str) or filename in ('', '.', '..') or filename.startswith('.')
                    or '/' in filename or '\\' in filename or any(ord(c) < 32 for c in filename)):
                raise ValueError(f'{folder}: filename must be a plain filename, without folders')
            sha = entry.get('sha256')
            if sha is not None and (not isinstance(sha, str) or not re.fullmatch('[a-fA-F0-9]{64}', sha)):
                raise ValueError(f'{folder}/{filename}: sha256 must contain 64 hexadecimal characters')
            dest = Path(comfyui) / 'models' / folder / filename
            if (folder, filename) in seen:
                raise ValueError(f'Duplicate destination: {folder}/{filename}')
            seen.add((folder, filename))
            models.append({'repo_id': f'{owner}/{repo}', 'repo_type': repo_type, 'revision': revision, 'remote': remote,
                           'dest': dest, 'sha256': sha.lower() if sha else None})
    return models


def progress_class():
    from tqdm.auto import tqdm
    class LoggedProgress(tqdm):
        def __init__(self, *args, **kwargs):
            self._progress_sink = open(os.devnull, 'w')
            self._last_report = time.monotonic()
            kwargs.update(file=self._progress_sink, disable=False)
            super().__init__(*args, **kwargs)
        def report(self):
            total = f'{self.total / 1e9:.2f} GB' if self.total else 'unknown size'
            print(f'[Models] {self.desc}: {self.n / 1e9:.2f} GB / {total}', flush=True)
        def update(self, amount=1):
            result = super().update(amount)
            if time.monotonic() - self._last_report >= 10:
                self.report()
                self._last_report = time.monotonic()
            return result
        def close(self):
            if getattr(self, '_progress_sink', None) is None or self._progress_sink.closed:
                return
            self.report()
            super().close()
            self._progress_sink.close()
    return LoggedProgress


def heartbeat(stop, label):
    elapsed = 0
    while not stop.wait(30):
        elapsed += 30
        print(f'[Models] {label}: download still active ({elapsed} seconds elapsed).', flush=True)


def download_all(manifest, comfyui, *, download=None, sleep=time.sleep):
    models = read_models(manifest, comfyui)
    if not models:
        print('[Models] No model URLs configured; skipping downloads.', flush=True)
        return
    extra = {}
    if download is None:
        from huggingface_hub import hf_hub_download
        download = hf_hub_download
        extra['tqdm_class'] = progress_class()
    failures = []
    for model in models:
        dest, sha = model['dest'], model['sha256']
        label = f'{dest.parent.name}/{dest.name}'
        if dest.is_file() and dest.stat().st_size > 0 and (not sha or digest(dest) == sha):
            print(f'[Models] Already present: {label}', flush=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        identity = json.dumps([model['repo_type'], model['repo_id'], model['revision'], model['remote'], sha])
        stage = Path(comfyui).parent / '.model-downloads' / hashlib.sha256(identity.encode()).hexdigest()
        # A persistent local_dir lets the HF client resume interrupted transfers.
        for attempt in range(1, 4):
            try:
                print(f'[Models] Downloading {label} (attempt {attempt}/3)', flush=True)
                stop = threading.Event()
                monitor = threading.Thread(target=heartbeat, args=(stop, label), daemon=True)
                monitor.start()
                try:
                    source = Path(download(repo_id=model['repo_id'], repo_type=model['repo_type'], filename=model['remote'],
                                           revision=model['revision'], local_dir=str(stage),
                                           endpoint='https://huggingface.co',
                                           token=os.environ.get('HF_TOKEN') or False, **extra))
                finally:
                    stop.set()
                    monitor.join(timeout=1)
                if not source.is_file() or source.stat().st_size == 0:
                    raise ValueError('empty download')
                if sha and digest(source) != sha:
                    source.unlink()
                    raise ValueError('SHA-256 mismatch')
                os.replace(source, dest)
                print(f'[Models] Ready: {label}', flush=True)
                break
            except Exception as exc:
                # Do not print exception bodies, which may contain signed URLs or tokens.
                print(f'[Models] {label}: {type(exc).__name__}; check the link, disk space, and HF_TOKEN/access for gated models.', flush=True)
                if attempt < 3:
                    sleep(attempt * 5)
        else:
            failures.append(label)
    if failures:
        raise RuntimeError('Failed model downloads: ' + ', '.join(failures) + '. Restart to retry; the ComfyUI interface stays available.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--comfyui', default='/workspace/ComfyUI')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.validate_only:
            models = read_models(args.manifest, args.comfyui)
            print(f'[Models] Valid manifest: {len(models)} configured files; no downloads performed.', flush=True)
        else:
            download_all(args.manifest, args.comfyui)
    except (ValueError, OSError, RuntimeError, ImportError) as exc:
        print(f'[Models] {exc}', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
