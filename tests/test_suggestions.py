import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.suggestions import generate_suggestions, prepare_context, SuggestionError


class SuggestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = create_app({'TESTING': True, 'SECRET_KEY': 'test',
                              'DATABASE': str(Path(cls.tmp.name) / 'test.sqlite'), 'OPENROUTER_API_KEY': 'test-key', 'AI_PROVIDER':'openrouter', 'AI_MODEL':'openrouter/free'})
        conn = sqlite3.connect(cls.app.config['DATABASE'])
        conn.executemany('INSERT INTO professionals(id,email,name,password) VALUES(?,?,?,?)', [(1,'one@test','One','unused'),(2,'two@test','Two','unused')])
        conn.commit();conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.app.config.update(OPENROUTER_API_KEY='test-key', AI_PROVIDER='openrouter',AI_MODEL='openrouter/free')
        conn = sqlite3.connect(self.app.config['DATABASE'])
        conn.execute('DELETE FROM appointments');conn.execute('DELETE FROM patients');conn.execute('DELETE FROM ai_usage')
        self.pid = conn.execute("INSERT INTO patients(professional_id,name,first_name,last_name,email,phone,general_notes,clinical_summary) VALUES(1,'Ana Pérez','Ana','Pérez','ana@example.com','123456789','Ana Pérez comparte avances. Escribir a ana@example.com.','Mejoras en autonomía')").lastrowid
        conn.execute("INSERT INTO appointments(patient_id,professional_id,starts_at,status,completion_notes,follow_up_reminder) VALUES(?,1,?,'completed','Conversamos sobre rutinas','Retomar autonomía')", (self.pid,(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()))
        conn.commit();conn.close()
        self.client=self.app.test_client();self.other=self.app.test_client()
        for client,uid in ((self.client,1),(self.other,2)):
            with client.session_transaction() as state: state.update(user_id=uid,csrf='csrf')
        self.headers={'X-CSRF-Token':'csrf'}
        self.path=f'/api/patients/{self.pid}'

    def test_context_is_private_and_only_previewed(self):
        with patch('app.generate_suggestions') as provider:
            response=self.client.post(self.path+'/suggestion-context',json={'session_topics':'Explorar aprendizajes'},headers=self.headers)
            self.assertEqual(response.status_code,200)
            context=response.json['context']
            for private in ('Ana Pérez','ana@example.com','123456789'):
                self.assertNotIn(private,context)
            self.assertIn('rutinas',context);self.assertIn('autonomía',context)
            self.assertEqual(response.json['included_sessions'],1)
            provider.assert_not_called()
        self.assertEqual(self.other.post(self.path+'/suggestion-context',json={},headers=self.headers).status_code,404)
        self.assertEqual(self.app.test_client().post(self.path+'/suggestions',json={}).status_code,401)

    def test_consent_ownership_and_limits(self):
        proposal='Podría ser valioso retomar lo ocurrido durante la semana y explorar qué recursos le ayudaron a organizar sus actividades.'
        with patch('app.generate_suggestions',return_value=proposal) as provider:
            for payload in ({'context':'Test'}, {'context':'Test','external_consent':'true'}):
                self.assertEqual(self.client.post(self.path+'/suggestions',json=payload,headers=self.headers).status_code,400)
            self.assertEqual(self.other.post(self.path+'/suggestions',json={'context':'Test','external_consent':True,'reviewed':True},headers=self.headers).status_code,404)
            provider.assert_not_called()
            payload={'context':'Texto revisado','external_consent':True,'reviewed':True}
            self.assertEqual(self.client.post(self.path+'/suggestions',json=payload).status_code,403)
            result=self.client.post(self.path+'/suggestions',json=payload,headers=self.headers)
            self.assertEqual(result.json['suggestion'],proposal)
            provider.assert_called_once_with('Texto revisado','test-key','openrouter/free',provider='openrouter',local_url='http://127.0.0.1:8081')
            self.assertEqual(self.client.post(self.path+'/suggestions',json=payload,headers=self.headers).status_code,429)

    def test_disabled_and_failure_are_explicit(self):
        payload={'context':'Texto revisado','external_consent':True,'reviewed':True}
        self.app.config['OPENROUTER_API_KEY']=''
        with patch('app.generate_suggestions') as provider:
            self.assertEqual(self.client.post(self.path+'/suggestions',json=payload,headers=self.headers).status_code,503)
            provider.assert_not_called()
        self.app.config['OPENROUTER_API_KEY']='test-key'
        with patch('app.generate_suggestions',side_effect=SuggestionError('Límite alcanzado',429)):
            self.assertEqual(self.client.post(self.path+'/suggestions',json=payload,headers=self.headers).status_code,429)

    def test_payload_is_bounded_and_output_validated(self):
        result=prepare_context({'name':'Ana','general_notes':'x'*20000},[{'starts_at':'2030-01-01','notes':'y'*10000} for _ in range(200)])
        self.assertLessEqual(len(result['context']),10000)
        self.assertTrue(result['truncated'])
        prose='Podría ser valioso explorar cómo vivió las situaciones de la semana, qué apoyos encontró y qué le gustaría retomar en el próximo encuentro.'
        answer={'choices':[{'message':{'content':prose},'finish_reason':'stop'}]}
        with patch('app.suggestions.urllib.request.urlopen') as network:
            network.return_value.__enter__.return_value.read.return_value=json.dumps(answer).encode()
            self.assertEqual(generate_suggestions('Revisado','secret','openrouter/free',provider='openrouter'),prose)
            req=network.call_args.args[0]
            self.assertEqual(req.full_url,'https://openrouter.ai/api/v1/chat/completions')
            self.assertIn('Revisado',json.loads(req.data)['messages'][-1]['content'])
            self.assertNotIn('response_format',json.loads(req.data))
            network.return_value.__enter__.return_value.read.return_value=b'{}'
            with self.assertRaises(SuggestionError):generate_suggestions('Revisado','secret','openrouter/free',provider='openrouter')
        with patch('app.suggestions.urllib.request.urlopen',side_effect=urllib.error.HTTPError('url',429,'limited',{},io.BytesIO(b'sensitive details'))):
            with self.assertRaises(SuggestionError) as error:generate_suggestions('Revisado','secret','openrouter/free',provider='openrouter')
            self.assertEqual(error.exception.status,429)
            self.assertNotIn('sensitive',str(error.exception))

    def test_local_does_not_require_external_consent_or_key(self):
        self.app.config.update(AI_PROVIDER='local',AI_MODEL='grulla-local',OPENROUTER_API_KEY='')
        context=self.client.post(self.path+'/suggestion-context',json={},headers=self.headers).json
        self.assertTrue(context['enabled'])
        self.assertFalse(context['external'])
        with patch('app.generate_suggestions',return_value='Podría conversarse acerca de sus intereses y de qué apoyos le resultaron útiles durante la semana.') as provider:
            result=self.client.post(self.path+'/suggestions',json={'context':'Texto local','reviewed':True,'external_consent':False},headers=self.headers)
            self.assertEqual(result.status_code,200)
            self.assertEqual(provider.call_args.kwargs['provider'],'local')
            self.assertEqual(provider.call_args.args[1],'')
        with self.assertRaises(SuggestionError):
            generate_suggestions('Texto','','grulla-local',local_url='https://external.example')
        with self.assertRaises(SuggestionError):
            generate_suggestions('Texto','key','paid-model',provider='openrouter')

    def test_production_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'GRULLA_DATA_DIR':directory,'GRULLA_SECRET_KEY':'persistent-test-key','GRULLA_SECURE_COOKIES':'1'}):
            app=create_app({'TESTING':True})
            self.assertEqual(app.config['DATABASE'],str(Path(directory).resolve()/'grulla.sqlite'))
            self.assertEqual(app.config['SECRET_KEY'],'persistent-test-key')
            self.assertTrue(app.config['SESSION_COOKIE_SECURE'])
            self.assertFalse((Path(directory)/'secret.key').exists())
