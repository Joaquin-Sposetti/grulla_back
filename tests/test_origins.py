import tempfile
import unittest
from pathlib import Path
from app import create_app


class OriginTests(unittest.TestCase):
    def test_multiple_origins_and_legacy_fallback(self):
        origins = ['https://centrogrulla.netlify.app', 'https://centrogrulla.com.ar', 'https://www.centrogrulla.com.ar']
        configurations = [
            ({'FRONTEND_ORIGINS': ', '.join(origins) + '/', 'FRONTEND_ORIGIN': 'https://old.example'}, origins),
            ({'FRONTEND_ORIGINS': '', 'FRONTEND_ORIGIN': 'http://localhost:8000'}, ['http://localhost:8000']),
        ]
        for config, accepted in configurations:
            with self.subTest(config=config), tempfile.TemporaryDirectory() as tmp:
                app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'DATABASE': str(Path(tmp) / 'test.sqlite'), **config})
                client = app.test_client()
                for origin in accepted:
                    response = client.options('/api/login', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST'})
                    self.assertEqual(response.status_code, 204)
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
                    self.assertEqual(response.headers['Access-Control-Allow-Credentials'], 'true')
                    response = client.post('/api/login', headers={'Origin': origin}, json={'email': 'nobody@example.com', 'password': 'invalid'})
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
                for origin in ['https://other.example', accepted[0] + '.evil.example', 'null']:
                    response = client.post('/api/login', headers={'Origin': origin}, json={})
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                self.assertNotIn('Access-Control-Allow-Origin', client.get('/api/health').headers)
