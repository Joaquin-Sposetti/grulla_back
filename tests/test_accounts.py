import sqlite3
import tempfile
import unittest
from pathlib import Path
from app import create_app
from werkzeug.security import generate_password_hash


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'test.sqlite')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path, 'SECRET_KEY': 'test'})
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO professionals(name,email,password,role) VALUES(?,?,?,'admin')", ('Admin','admin@test.local',generate_password_hash('admin-password', method='pbkdf2:sha256')))
        conn.close()
        self.admin = self.app.test_client()
        response = self.admin.post('/api/login', json={'email':'admin@test.local','password':'admin-password'})
        self.assertEqual(response.json['user']['role'], 'admin')
        self.headers = {'X-CSRF-Token':response.json['csrf']}

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **extra):
        return self.admin.post('/api/admin/professionals', headers=self.headers, json={'name':'Sofia','email':'sofia@test.local','password':'professional-password',**extra})

    def test_create_login_permissions_and_validation(self):
        self.assertEqual(self.app.test_client().get('/api/admin/professionals').status_code, 401)
        self.assertEqual(self.admin.post('/api/admin/professionals', json={}).status_code, 403)
        self.assertEqual(self.admin.post('/api/admin/professionals', headers={**self.headers, 'Origin':'https://other.example'}, json={}).status_code, 403)
        self.assertEqual(self.create(role='admin').status_code, 400)
        self.assertEqual(self.create(password='short').status_code, 400)
        self.assertEqual(self.create(email='invalid').status_code, 400)
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create(email='SOFIA@test.local').status_code, 409)
        professional = self.app.test_client()
        response = professional.post('/api/login', json={'email':'sofia@test.local','password':'professional-password'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['user']['role'], 'professional')
        headers = {'X-CSRF-Token': response.json['csrf']}
        self.assertEqual(professional.get('/api/admin/professionals').status_code, 403)
        self.assertEqual(professional.post('/api/admin/professionals', json={}, headers=headers).status_code, 403)
        self.assertEqual(professional.put('/api/admin/professionals/1', json={'role':'admin'}, headers=headers).status_code, 403)
        rows = self.admin.get('/api/admin/professionals').json
        self.assertTrue(all('password' not in row and 'session_version' not in row for row in rows))
        self.assertEqual(self.admin.put('/api/admin/professionals/1', headers=self.headers, json={'active':False}).status_code, 403)

    def test_disable_reactivate_reset_and_data_preservation(self):
        uid = self.create().json['id']
        client = self.app.test_client()
        def login(password='professional-password'):
            return client.post('/api/login', json={'email':'sofia@test.local','password':password})
        response = login()
        h = {'X-CSRF-Token': response.json['csrf']}
        patient = client.post('/api/patients', headers=h, json={'name':'Preserved'}).json['id']
        def update(data):
            return self.admin.put(f'/api/admin/professionals/{uid}', headers=self.headers, json=data)
        self.assertEqual(update({'active':'false'}).status_code,400)
        self.assertEqual(update({'role':'admin'}).status_code,400)
        self.assertEqual(update({'email':'admin@test.local'}).status_code,409)
        self.assertEqual(update({'active':False}).status_code,200)
        self.assertEqual(client.get('/api/me').status_code,401)
        self.assertEqual(login().status_code,401)
        self.assertEqual(update({'active':True}).status_code,200)
        self.assertEqual(login().status_code,200)
        self.assertEqual(client.get('/api/patients').json[0]['id'], patient)
        self.assertEqual(update({'password':'new-password-123'}).status_code,200)
        self.assertEqual(client.get('/api/patients').status_code,401)
        self.assertEqual(login().status_code,401)
        self.assertEqual(login('new-password-123').status_code,200)
        self.assertEqual(client.get('/api/patients').json[0]['id'],patient)

    def test_promote_existing_account_preserves_id_and_requires_confirmation(self):
        uid = self.create().json['id']
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM professionals WHERE role='admin'")
        conn.close()
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['create-admin'], input='Sofia\nsofia@test.local\nn\n')
        self.assertNotEqual(result.exit_code,0)
        result = runner.invoke(args=['create-admin'], input='Sofia\nsofia@test.local\ny\nnew-admin-password\nnew-admin-password\n')
        self.assertEqual(result.exit_code,0,result.output)
        response = self.app.test_client().post('/api/login',json={'email':'sofia@test.local','password':'new-admin-password'})
        self.assertEqual(response.json['user']['id'],uid)
        self.assertEqual(response.json['user']['role'],'admin')

    def test_bootstrap_is_single_admin(self):
        result = self.app.test_cli_runner().invoke(args=['create-admin'])
        self.assertNotEqual(result.exit_code,0)
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM professionals WHERE role='admin'")
        conn.close()
        result = self.app.test_cli_runner().invoke(args=['create-admin'], input='Joaquin\nJOAQUIN@test.local\nadmin-password-123\nadmin-password-123\n')
        self.assertEqual(result.exit_code,0,result.output)
        result = self.app.test_client().post('/api/login',json={'email':'joaquin@test.local','password':'admin-password-123'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['user']['role'],'admin')

    def test_legacy_database_migration_preserves_accounts(self):
        legacy = str(Path(self.tmp.name) / 'legacy.sqlite')
        with sqlite3.connect(legacy) as conn:
            conn.execute('CREATE TABLE professionals(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL)')
            conn.execute('INSERT INTO professionals VALUES(1,?,?,?)',('legacy@test','Legacy',generate_password_hash('legacy-password',method='pbkdf2:sha256')))
        conn.close()
        for _ in range(2):
            app = create_app({'TESTING':True,'DATABASE':legacy,'SECRET_KEY':'test'})
        client = app.test_client()
        response = client.post('/api/login',json={'email':'legacy@test','password':'legacy-password'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['user']['role'],'professional')
        self.assertEqual(client.get('/api/admin/professionals').status_code,403)
