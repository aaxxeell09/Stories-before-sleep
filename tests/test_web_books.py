import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_app import App, validate
from web_books import book_id

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII=')


class BookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.folder = root / 'book'
        (self.folder / 'images').mkdir(parents=True)
        self.book = {'story': {'title': 'A little book', 'full_story_text': 'Together.',
                              'what_we_learned': 'Share.', 'try_it_today': 'Take turns.'},
                     'pages': [{'page_number': i, 'narration': f'Page {i}', 'dialogue': [],
                                'image_description': 'A test image'} for i in (1, 2)]}
        (self.folder / 'storybook.json').write_text(json.dumps(self.book))
        (self.folder / 'images/page-001.png').write_bytes(PNG)
        self.manifest = {'status': 'failed', 'pages': [{'page_number': 1, 'image': 'images/page-001.png'}]}
        self.save_manifest()
        self.server = App(('127.0.0.1', 0), [root])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.route = '/api/books/' + book_id(self.folder)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def save_manifest(self):
        (self.folder / 'manifest.json').write_text(json.dumps(self.manifest))

    def fetch(self, path):
        with urlopen(self.url + path) as response:
            return json.load(response)

    def test_partial_book_and_image_are_readable(self):
        self.assertIn('A little book', [b['title'] for b in self.fetch('/api/books')['books']])
        book = self.fetch(self.route)
        self.assertEqual([p['page_number'] for p in book['pages']], [1, 2])
        self.assertEqual(book['status'], 'failed')
        self.assertIsNone(book['pages'][1]['image'])
        with urlopen(self.url + book['pages'][0]['image']) as response:
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertEqual(response.read(), PNG)
        self.assertNotIn(str(self.folder), json.dumps(book))

    def test_rejects_manifest_traversal_and_symlink(self):
        outside = Path(self.temp.name) / 'private.png'
        outside.write_bytes(PNG)
        (self.folder / 'images/link.png').symlink_to(outside)
        for path in ('../private.png', str(outside), 'images/link.png'):
            self.manifest['pages'][0]['image'] = path
            self.save_manifest()
            self.assertIsNone(self.fetch(self.route)['pages'][0]['image'])
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + self.route + '/images/1')
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_failure_exposes_safe_actionable_status(self):
        self.manifest.update(failed_page=2, error={'code': 'rate_limit_exceeded', 'message': 'private-provider-details'})
        self.save_manifest()
        book = self.fetch(self.route)
        self.assertEqual(book['images_ready'], 1)
        self.assertEqual(book['failed_page'], 2)
        self.assertIn('rate limit', book['image_error'])
        self.assertNotIn('private-provider-details', json.dumps(book))
        self.manifest['status'] = 'preview_complete'
        self.save_manifest()
        self.assertIsNone(self.fetch(self.route)['image_error'])

    def test_refresh_reads_newly_completed_pages(self):
        self.assertIsNone(self.fetch(self.route)['pages'][1]['image'])
        (self.folder / 'images/page-002.png').write_bytes(PNG)
        self.manifest.update(status='complete', pages=self.manifest['pages'] + [{'page_number': 2, 'image': 'images/page-002.png'}])
        self.save_manifest()
        self.assertEqual(self.fetch(self.route)['status'], 'complete')
        self.assertIsNotNone(self.fetch(self.route)['pages'][1]['image'])

    def test_illustrated_age_validation_does_not_limit_text_only(self):
        payload = dict(kind='generate', age=5, minutes=2, rhyme=False, lesson='Share', illustrated=True)
        with self.assertRaisesRegex(ValueError, 'ages 2–4'):
            validate(payload)
        payload['illustrated'] = False
        self.assertEqual(validate(payload)['age'], 5)
