import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_app import App, validate


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = App(('127.0.0.1', 0))
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_static_and_status(self):
        for path in ('/', '/app.js', '/style.css', '/api/status'):
            with urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)
        with urlopen(self.url + '/api/status') as response:
            self.assertNotIn('APIKEY=', response.read().decode())

    def test_validation(self):
        for age in (-1, 19, True, 3.5):
            with self.assertRaises(ValueError):
                validate(dict(kind='generate', age=age, minutes=2, rhyme=False, lesson='Sharing'))
        with self.assertRaises(ValueError):
            validate(dict(kind='memory', dataset=''))

    def test_cross_origin_and_private_files(self):
        for request in (Request(self.url + '/api/jobs', data=b'{}', headers={'Content-Type':'application/json', 'Origin':'https://elsewhere.example'}), Request(self.url + '/.env')):
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertIn(error.exception.code, (403, 404))

    def test_missing_configuration(self):
        data = dict(kind='generate', age=3, minutes=2, rhyme=False, lesson='Sharing')
        with patch('web_app.missing', return_value=['ROCKETRIDE_APIKEY']):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url + '/api/jobs', data=json.dumps(data).encode(), headers={'Content-Type':'application/json'}))
            self.assertEqual(error.exception.code, 400)

    def test_worker_success_and_failure(self):
        from types import SimpleNamespace
        with patch('web_app.subprocess.run', return_value=SimpleNamespace(stdout='{"story":"A story"}', returncode=0)):
            self.server.run_job('success', {})
        self.assertEqual(self.server.jobs.pop('success')['result']['story'], 'A story')
        with patch('web_app.subprocess.run', return_value=SimpleNamespace(stdout='{"error":"Service failed"}', returncode=1)):
            self.server.run_job('failure', {})
        self.assertEqual(self.server.jobs.pop('failure')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
