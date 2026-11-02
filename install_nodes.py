"""Install the optional audited node commits at build time; never at pod startup."""
import json
import pathlib
import subprocess
import sys

root = pathlib.Path('/opt/comfyui-seed/custom_nodes')
for node in json.loads(pathlib.Path('/opt/template/nodes.lock.json').read_text()):
    dest = root / node['name']
    subprocess.run(['git', 'init', str(dest)], check=True)
    subprocess.run(['git', '-C', str(dest), 'remote', 'add', 'origin', node['url']], check=True)
    subprocess.run(['git', '-C', str(dest), 'fetch', '--depth', '1', 'origin', node['commit']], check=True)
    subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    requirements = dest / 'requirements.txt'
    if requirements.is_file():
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-c', '/opt/constraints.txt',
                        '-r', str(requirements)], check=True, cwd=dest)
