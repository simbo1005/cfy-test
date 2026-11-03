"""Allow browser navigation to the homepage through hosting dashboards."""
import argparse
import ast
from pathlib import Path

OLD = """            if sec_fetch_site == 'cross-site':
                return web.Response(status=403)"""
NEW = """            # Dashboard links and reloads can retain cross-site navigation headers.
            homepage_navigation = (
                request.method in ('GET', 'HEAD')
                and request.path == '/'
                and request.headers.get('Sec-Fetch-Mode') == 'navigate'
            )
            if sec_fetch_site == 'cross-site' and not homepage_navigation:
                return web.Response(status=403)"""


def apply(comfyui):
    path = Path(comfyui) / 'server.py'
    source = path.read_text()
    if source.count(NEW) == 1 and OLD not in source:
        return False
    if source.count(OLD) != 1 or NEW in source:
        raise ValueError('Unrecognized ComfyUI origin middleware; refusing to change server.py.')
    updated = source.replace(OLD, NEW, 1)
    ast.parse(updated)
    path.write_text(updated)
    print('[Proxy] Enabled homepage navigation from hosting dashboards.', flush=True)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--comfyui', required=True)
    apply(parser.parse_args().comfyui)
