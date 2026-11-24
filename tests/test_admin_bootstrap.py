import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import check_password_hash
from app import create_app


class AdminBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'TESTING':True, 'SECRET_KEY':'test', 'DATABASE':str(Path(self.tmp.name) / 'test.sqlite')}
        self.env = {
            'GRULLA_INITIAL_ADMIN_NAME':'Joaquin',
            'GRULLA_INITIAL_ADMIN_EMAIL':'ADMIN@example.com',
            'GRULLA_INITIAL_ADMIN_PASSWORD':'test-private-password',
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_creation_persistence_and_no_overwrite(self):
        with patch.dict(os.environ, self.env):
            app = create_app(self.config)
        with closing(sqlite3.connect(self.config['DATABASE'])) as conn:
            row = conn.execute('SELECT email,password,role FROM professionals').fetchone()
            self.assertEqual(row[0], 'admin@example.com')
            self.assertEqual(row[2], 'admin')
            self.assertNotEqual(row[1], self.env['GRULLA_INITIAL_ADMIN_PASSWORD'])
            self.assertTrue(check_password_hash(row[1], self.env['GRULLA_INITIAL_ADMIN_PASSWORD']))
        with patch.dict(os.environ, {**self.env, 'GRULLA_INITIAL_ADMIN_EMAIL':'other@example.com', 'GRULLA_INITIAL_ADMIN_PASSWORD':'different-password'}):
            create_app(self.config)
        # Removing the provisioning variables must not remove or change the account.
        with patch.dict(os.environ, {}, clear=True):
            app = create_app(self.config)
        client = app.test_client()
        response = client.post('/api/login', json={'email':'admin@example.com', 'password':self.env['GRULLA_INITIAL_ADMIN_PASSWORD']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['user']['role'],'admin')
        self.assertEqual(len(client.get('/api/admin/professionals').json),1)

    def test_invalid_settings_do_not_create_accounts_or_expose_password(self):
        for replacement in ({'GRULLA_INITIAL_ADMIN_NAME':''}, {'GRULLA_INITIAL_ADMIN_EMAIL':'invalid'}, {'GRULLA_INITIAL_ADMIN_PASSWORD':'short'}):
            values = {**self.env, **replacement}
            with self.subTest(replacement=replacement), patch.dict(os.environ, values):
                with self.assertRaises(RuntimeError) as raised:
                    create_app(self.config)
                self.assertNotIn(values['GRULLA_INITIAL_ADMIN_PASSWORD'], str(raised.exception))
        with closing(sqlite3.connect(self.config['DATABASE'])) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM professionals').fetchone()[0],0)

    def test_existing_professional_is_not_promoted_or_overwritten(self):
        create_app(self.config)
        with closing(sqlite3.connect(self.config['DATABASE'])) as conn:
            conn.execute('INSERT INTO professionals(name,email,password) VALUES(?,?,?)', ('Existing','admin@example.com','unchanged'))
            conn.commit()
        with patch.dict(os.environ,self.env), self.assertRaises(RuntimeError):
            create_app(self.config)
        with closing(sqlite3.connect(self.config['DATABASE'])) as conn:
            self.assertEqual(conn.execute('SELECT role,password FROM professionals').fetchone(),('professional','unchanged'))
