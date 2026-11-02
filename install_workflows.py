"""Seed saved UI workflows without overwriting user files."""
import argparse
import json
import os
from pathlib import Path
import tempfile


def install(source, destination):
    source, destination = Path(source), Path(destination)
    for path in sorted(source.rglob('*.json')):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source)
        target = destination / relative
        if target.exists():
            continue
        data = path.read_bytes()
        workflow = json.loads(data)
        if not isinstance(workflow, dict) or not isinstance(workflow.get('nodes'), list):
            raise ValueError(f'{relative}: use an ordinary UI workflow export with a nodes list')
        target.parent.mkdir(parents=True, exist_ok=True)
        # A complete file appears atomically; a concurrent/user file is never overwritten.
        fd, temporary = tempfile.mkstemp(prefix='.workflow-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
            try:
                os.link(temporary, target)
                print(f'[Workflows] Added {relative}', flush=True)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    install(args.source, args.destination)
