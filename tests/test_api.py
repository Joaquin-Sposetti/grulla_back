import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app import create_app
from werkzeug.security import generate_password_hash


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATABASE': str(Path(self.tmp.name)/'test.sqlite'), 'SECRET_KEY': 'test'})
        with self.app.app_context():
            import sqlite3
            conn = sqlite3.connect(self.app.config['DATABASE'])
            for uid in (1,2):
                conn.execute('INSERT INTO professionals(id,email,name,password) VALUES(?,?,?,?)',(uid,f'{uid}@test.local',f'Professional {uid}',generate_password_hash('secure-password',method='pbkdf2:sha256')))
            conn.commit(); conn.close()
        self.a = self.app.test_client(); self.b = self.app.test_client()
        self.ha = self.login(self.a,1); self.hb = self.login(self.b,2)

    def tearDown(self):
        self.tmp.cleanup()

    def login(self, client, uid):
        response = client.post('/api/login', json={'email':f'{uid}@test.local','password':'secure-password'})
        self.assertEqual(response.status_code,200)
        return {'X-CSRF-Token':response.json['csrf']}

    def create_patient(self):
        r=self.a.post('/api/patients',json={'name':'Patient','general_notes':'Private'},headers=self.ha)
        self.assertEqual(r.status_code,201)
        return r.json['id']

    def test_isolation_and_cascade(self):
        pid=self.create_patient()
        start=(datetime.now(timezone.utc)+timedelta(minutes=45)).isoformat()
        r=self.a.post('/api/sessions',json={'patient_id':pid,'starts_at':start,'notes':'Private session'},headers=self.ha)
        self.assertEqual(r.status_code,201); sid=r.json['id']
        for route in ('patients','sessions','reminders'):
            self.assertEqual(self.b.get('/api/'+route).json,[])
        for path in (f'/api/patients/{pid}',f'/api/sessions/{sid}'):
            self.assertEqual(self.b.put(path,json={'name':'Attack'},headers=self.hb).status_code,404)
            self.assertEqual(self.b.delete(path,headers=self.hb).status_code,404)
        self.assertEqual(self.b.post('/api/sessions',json={'patient_id':pid,'starts_at':start},headers=self.hb).status_code,400)
        self.assertEqual(len(self.a.get('/api/reminders').json),1)
        self.assertEqual(self.a.delete(f'/api/patients/{pid}',headers=self.ha).status_code,200)
        self.assertEqual(self.a.get('/api/sessions').json,[])

    def test_auth_csrf_and_origin(self):
        self.assertEqual(self.app.test_client().get('/api/patients').status_code,401)
        self.assertEqual(self.a.post('/api/patients',json={'name':'Patient'}).status_code,403)
        self.assertEqual(self.a.post('/api/patients',json={'name':'Patient'},headers={**self.ha,'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.a.post('/api/register',json={}).status_code,403)
        self.assertEqual(self.a.get('/api/me').json['user']['id'],1)
        self.a.post('/api/logout',headers=self.ha)
        self.assertEqual(self.a.get('/api/me').status_code,401)

    def test_updates_validation_and_reminders(self):
        pid=self.create_patient()
        self.assertEqual(self.a.put(f'/api/patients/{pid}',json={'name':'Updated'},headers=self.ha).status_code,200)
        self.assertEqual(self.a.get('/api/patients').json[0]['name'],'Updated')
        self.assertEqual(self.a.post('/api/patients',json={'name':''},headers=self.ha).status_code,400)
        self.assertEqual(self.a.post('/api/sessions',json={'patient_id':pid,'starts_at':'bad'},headers=self.ha).status_code,400)
        start=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        data={'patient_id':pid,'starts_at':start,'notes':'Initial'}
        sid=self.a.post('/api/sessions',json=data,headers=self.ha).json['id']
        data.update(notes='Follow-up',status='completed')
        self.assertEqual(self.a.put(f'/api/sessions/{sid}',json=data,headers=self.ha).status_code,200)
        self.assertEqual(self.a.get('/api/sessions').json[0]['notes'],'Follow-up')
        self.assertEqual(self.a.get('/api/reminders').json,[])

    def test_session_future_time_and_duration(self):
        pid = self.create_patient()
        for start in ((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(), '2026-10-08', 'bad'):
            r = self.a.post('/api/sessions', json={'patient_id':pid, 'starts_at':start}, headers=self.ha)
            self.assertEqual(r.status_code, 400)
        future = (datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
        for duration in (0, 4, 481, 'invalid'):
            self.assertEqual(self.a.post('/api/sessions',json={'patient_id':pid,'starts_at':future,'duration':duration},headers=self.ha).status_code,400)
        sid = self.a.post('/api/sessions',json={'patient_id':pid,'starts_at':future,'duration':45},headers=self.ha).json['id']
        self.assertEqual(self.a.get('/api/sessions').json[0]['duration'],45)
        past = (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        self.assertEqual(self.a.put(f'/api/sessions/{sid}',json={'patient_id':pid,'starts_at':past},headers=self.ha).status_code,400)
        import sqlite3
        conn = sqlite3.connect(self.app.config['DATABASE'])
        conn.execute('UPDATE appointments SET starts_at=? WHERE id=?',(past,sid));conn.commit();conn.close()
        self.assertEqual(self.a.put(f'/api/sessions/{sid}',json={'patient_id':pid,'starts_at':past,'notes':'Observaciones posteriores'},headers=self.ha).status_code,200)

    def test_patient_names_and_birth_date(self):
        data = {'first_name':'Ana María', 'last_name':'Pérez López', 'birth_date':'2000-02-29'}
        created = self.a.post('/api/patients',json=data,headers=self.ha)
        self.assertEqual(created.status_code,201)
        patient = self.a.get('/api/patients').json[0]
        self.assertEqual(patient['name'],'Ana María Pérez López')
        self.assertEqual(patient['first_name'],'Ana María')
        self.assertEqual(patient['last_name'],'Pérez López')
        self.assertEqual(patient['birth_date'],'2000-02-29')
        for birth in ('2001-02-29','2000-13-01','2999-01-01'):
            self.assertEqual(self.a.post('/api/patients',json={**data,'birth_date':birth},headers=self.ha).status_code,400)
        self.assertEqual(self.a.post('/api/patients',json={**data,'last_name':''},headers=self.ha).status_code,400)
        self.assertEqual(self.a.put(f"/api/patients/{created.json['id']}",json={**data,'first_name':'Ana'},headers=self.ha).status_code,200)
        self.assertEqual(self.a.get('/api/patients').json[0]['name'],'Ana Pérez López')

    def test_one_hour_reminder_from_last_completed_session(self):
        import sqlite3
        pid = self.create_patient()
        now = datetime.now(timezone.utc)
        prior = {'patient_id':pid,'starts_at':(now+timedelta(days=2)).isoformat(),'status':'completed','follow_up_reminder':'Retomar avances de la semana'}
        previous_id = self.a.post('/api/sessions',json=prior,headers=self.ha).json['id']
        conn=sqlite3.connect(self.app.config['DATABASE'])
        conn.execute('UPDATE appointments SET starts_at=? WHERE id=?',((now-timedelta(days=1)).isoformat(),previous_id));conn.commit()
        upcoming = {'patient_id':pid,'starts_at':(now+timedelta(minutes=30)).isoformat()}
        sid = self.a.post('/api/sessions',json=upcoming,headers=self.ha).json['id']
        self.a.post('/api/sessions',json={**upcoming,'starts_at':(now+timedelta(minutes=61)).isoformat()},headers=self.ha)
        self.a.post('/api/sessions',json={**upcoming,'status':'cancelled'},headers=self.ha)
        reminders=self.a.get('/api/reminders').json
        self.assertEqual([r['id'] for r in reminders],[sid])
        self.assertEqual(reminders[0]['patient_name'],'Patient')
        self.assertEqual(reminders[0]['reminder'],'Retomar avances de la semana')
        self.assertEqual(self.b.get('/api/reminders').json,[])
        # A newer completed session without a reminder clears the previous suggestion.
        newer=self.a.post('/api/sessions',json={**prior,'follow_up_reminder':''},headers=self.ha).json['id']
        conn.execute('UPDATE appointments SET starts_at=? WHERE id=?',((now-timedelta(hours=2)).isoformat(),newer));conn.commit()
        self.assertEqual(self.a.get('/api/reminders').json[0]['reminder'],'')
        conn.close()
        # An optional reminder remains when older clients update other fields.
        old_start=(now-timedelta(days=1)).isoformat()
        self.a.put(f'/api/sessions/{previous_id}',json={'patient_id':pid,'starts_at':old_start,'status':'completed'},headers=self.ha)
        saved=next(s for s in self.a.get('/api/sessions').json if s['id']==previous_id)
        self.assertEqual(saved['follow_up_reminder'],'Retomar avances de la semana')

    def test_finish_session_and_save_closure(self):
        pid=self.create_patient()
        data={'patient_id':pid,'starts_at':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(),'notes':'Temas planificados'}
        sid=self.a.post('/api/sessions',json=data,headers=self.ha).json['id']
        path=f'/api/sessions/{sid}/complete'
        self.assertEqual(self.b.post(path,json={},headers=self.hb).status_code,404)
        self.assertEqual(self.a.post(path,json={}).status_code,403)
        self.assertEqual(self.a.post(path,json={},headers=self.ha).status_code,200)
        row=self.a.get('/api/sessions').json[0]
        self.assertEqual(row['status'],'completed')
        self.assertEqual(row['completion_notes'],'')
        self.assertEqual(self.a.get('/api/reminders').json,[])
        closure={'completion_notes':'Conversamos sobre avances','follow_up_reminder':'Retomar objetivos'}
        self.assertEqual(self.a.post(path,json=closure,headers=self.ha).status_code,200)
        # Repeated clicks preserve the saved closure and planned topics.
        self.a.post(path,json={},headers=self.ha)
        row=self.a.get('/api/sessions').json[0]
        self.assertEqual(row['completion_notes'],closure['completion_notes'])
        self.assertEqual(row['follow_up_reminder'],closure['follow_up_reminder'])
        self.assertEqual(row['notes'],'Temas planificados')
        cancelled=self.a.post('/api/sessions',json={**data,'status':'cancelled'},headers=self.ha).json['id']
        self.assertEqual(self.a.post(f'/api/sessions/{cancelled}/complete',json={},headers=self.ha).status_code,409)

    def test_reminder_exact_window_and_timezone_offsets(self):
        import sqlite3
        from unittest.mock import patch
        pid=self.create_patient()
        other=self.b.post('/api/patients',json={'name':'Other'},headers=self.hb).json['id']
        fixed=datetime(2030,1,2,23,30,tzinfo=timezone.utc)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
        conn=sqlite3.connect(self.app.config['DATABASE'])
        expected=[]
        cases=[(-1,'scheduled',1,pid,False),(0,'scheduled',1,pid,False),(30,'scheduled',1,pid,True),(60,'scheduled',1,pid,True),(61,'scheduled',1,pid,False),(15,'completed',1,pid,False),(20,'cancelled',1,pid,False),(30,'scheduled',2,other,False)]
        for minutes,status,owner,patient_id,include in cases:
            # Alternate offsets: reminder comparisons must use instants, not strings.
            start=(fixed+timedelta(minutes=minutes)).astimezone(timezone(timedelta(hours=-3 if minutes==30 else 2))).isoformat()
            sid=conn.execute('INSERT INTO appointments(patient_id,professional_id,starts_at,status) VALUES(?,?,?,?)',(patient_id,owner,start,status)).lastrowid
            if include:expected.append(sid)
        conn.commit();conn.close()
        with patch('app.datetime',Clock):
            response=self.a.get('/api/reminders')
        self.assertEqual([r['id'] for r in response.json],expected)
        self.assertEqual(response.headers['X-Reminder-Window-Start'],fixed.isoformat())
        self.assertEqual(response.headers['X-Reminder-Window-End'],(fixed+timedelta(hours=1)).isoformat())

    def test_patient_history_and_private_summary(self):
        pid=self.create_patient();path=f'/api/patients/{pid}/history'
        self.assertEqual(self.app.test_client().get(path).status_code,401)
        self.assertEqual(self.b.get(path).status_code,404)
        self.assertEqual(self.b.put(path,json={'clinical_summary':'Intrusion'},headers=self.hb).status_code,404)
        self.assertEqual(self.a.put(path,json={'clinical_summary':'Summary'}).status_code,403)
        self.assertEqual(self.a.put(path,json={'clinical_summary':'Resumen del proceso'},headers=self.ha).status_code,200)
        data={'patient_id':pid,'starts_at':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),'notes':'Temas planificados'}
        sid=self.a.post('/api/sessions',json=data,headers=self.ha).json['id']
        self.a.post(f'/api/sessions/{sid}/complete',json={'completion_notes':'Anotaciones clínicas','follow_up_reminder':'Temas próximos'},headers=self.ha)
        other=self.a.post('/api/patients',json={'name':'Other patient'},headers=self.ha).json['id']
        self.a.post('/api/sessions',json={**data,'patient_id':other},headers=self.ha)
        history=self.a.get(path).json
        self.assertEqual(history['patient']['clinical_summary'],'Resumen del proceso')
        self.assertEqual(history['patient']['general_notes'],'Private')
        self.assertEqual(history['patient']['professional_name'],'Professional 1')
        self.assertEqual(len(history['sessions']),1)
        self.assertEqual(history['sessions'][0]['completion_notes'],'Anotaciones clínicas')
        self.assertEqual(history['sessions'][0]['follow_up_reminder'],'Temas próximos')
        self.assertEqual(history['sessions'][0]['notes'],'Temas planificados')
        self.assertEqual(self.a.put(path,json={'clinical_summary':'x'*5001},headers=self.ha).status_code,400)
        self.a.put(f'/api/patients/{pid}',json={'name':'Updated name'},headers=self.ha)
        self.assertEqual(self.a.get(path).json['patient']['clinical_summary'],'Resumen del proceso')
        self.a.delete(f'/api/patients/{pid}',headers=self.ha)
        self.assertEqual(self.a.get(path).status_code,404)

    def test_overdue_sessions_use_end_time_and_professional(self):
        import sqlite3
        from unittest.mock import patch
        pid=self.create_patient()
        other=self.b.post('/api/patients',json={'name':'Other'},headers=self.hb).json['id']
        fixed=datetime(2030,1,2,12,0,tzinfo=timezone.utc)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
        conn=sqlite3.connect(self.app.config['DATABASE']);expected=[]
        cases=[(-61,60,'scheduled',1,pid,True),(-60,60,'scheduled',1,pid,True),(-30,60,'scheduled',1,pid,False),(-61,90,'scheduled',1,pid,False),(15,60,'scheduled',1,pid,False),(-90,60,'completed',1,pid,False),(-90,60,'cancelled',1,pid,False),(-90,60,'scheduled',2,other,False)]
        for minutes,duration,status,owner,patient_id,include in cases:
            start=(fixed+timedelta(minutes=minutes)).astimezone(timezone(timedelta(hours=-3))).isoformat()
            sid=conn.execute('INSERT INTO appointments(patient_id,professional_id,starts_at,duration,status) VALUES(?,?,?,?,?)',(patient_id,owner,start,duration,status)).lastrowid
            if include:expected.append(sid)
        conn.commit();conn.close()
        self.assertEqual(self.app.test_client().get('/api/overdue-sessions').status_code,401)
        with patch('app.datetime',Clock):
            response=self.a.get('/api/overdue-sessions')
            self.assertEqual([r['id'] for r in response.json],expected)
            self.assertEqual(response.json[0]['patient_name'],'Patient')
            self.assertEqual(datetime.fromisoformat(response.json[0]['ends_at']),fixed-timedelta(minutes=1))
            self.a.post(f'/api/sessions/{expected[0]}/complete',json={},headers=self.ha)
            self.assertEqual([r['id'] for r in self.a.get('/api/overdue-sessions').json],expected[1:])

    def test_rate_limit(self):
        client=self.app.test_client()
        for _ in range(10):
            self.assertEqual(client.post('/api/login',json={'email':'unknown','password':'bad'}).status_code,401)
        self.assertEqual(client.post('/api/login',json={'email':'unknown','password':'bad'}).status_code,429)


if __name__ == '__main__':
    unittest.main()
