"""Check the scoped source patch without importing inference dependencies."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('proxy_fix', ROOT / 'apply_proxy_fix.py')
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)


class ProxyFixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Representative surrounding code verifies the exact guarded replacement.
        self.original = ("async def middleware(request, handler):\n"
                         "    if 'Sec-Fetch-Site' in request.headers:\n"
                         "        sec_fetch_site = request.headers['Sec-Fetch-Site']\n"
                         "        if True:\n" + fix.OLD + "\n"
                         "    if request.headers.get('Origin') == 'blocked-origin':\n"
                         "        return web.Response(status=403)\n"
                         "    return await handler(request)\n")
        (self.root / 'server.py').write_text(self.original)

    def test_idempotent_and_preserves_surrounding_code(self):
        self.assertTrue(fix.apply(self.root))
        updated = (self.root / 'server.py').read_text()
        self.assertEqual(updated.replace(fix.NEW, fix.OLD), self.original)
        self.assertFalse(fix.apply(self.root))
        self.assertEqual((self.root / 'server.py').read_text(), updated)

    def test_unknown_source_is_not_changed(self):
        path = self.root / 'server.py'
        path.write_text('custom = True\n')
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            fix.apply(self.root)
        self.assertEqual(path.read_text(), 'custom = True\n')

    def test_navigation_only_and_existing_origin_check(self):
        fix.apply(self.root)
        scope = {'web': SimpleNamespace(Response=lambda status: status)}
        exec((self.root / 'server.py').read_text(), scope)
        async def handler(request):
            return 200
        for method, path, site, mode, origin, expected in (
            ('GET', '/', 'cross-site', 'navigate', '', 200),
            ('HEAD', '/', 'cross-site', 'navigate', '', 200),
            ('GET', '/?ignored', 'cross-site', 'navigate', '', 403),
            ('POST', '/', 'cross-site', 'navigate', '', 403),
            ('POST', '/prompt', 'cross-site', 'navigate', '', 403),
            ('GET', '/system_stats', 'cross-site', 'navigate', '', 403),
            ('GET', '/', 'cross-site', 'cors', '', 403),
            ('GET', '/', 'cross-site', '', '', 403),
            ('GET', '/', 'cross-site', 'navigate', 'blocked-origin', 403),
            ('GET', '/', 'same-origin', 'navigate', '', 200),
            ('GET', '/', '', '', '', 200),
        ):
            with self.subTest(method=method, path=path, site=site, mode=mode, origin=origin):
                headers = {'Sec-Fetch-Site': site, 'Sec-Fetch-Mode': mode, 'Origin': origin}
                req = SimpleNamespace(method=method, path=path, headers=headers)
                self.assertEqual(asyncio.run(scope['middleware'](req, handler)), expected)
