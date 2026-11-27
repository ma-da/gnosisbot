#!/usr/bin/env python3
"""Operator-only completion diagnostics, recovery and explicitly selected admin email canary."""
import os,sys,json,argparse
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.config import get_settings
from gnosis_platform.db import connect
from gnosis_platform.reading_completion import drain,processing_lock,enabled
from gnosis_platform.certificate_store import verify_record,stamp
from gnosis_platform.certificate_validation import need
from gnosis_platform.completion_outbox import enqueue_after_settlement,dispatch_one,suppress_legacy
from gnosis_platform.reading_results_email import prepared_message
from gnosis_platform.account_email import decrypt_email,mask_email


def candidates(db):
    legacy_gate="AND NOT EXISTS(SELECT 1 FROM ibm_trial_email_notifications t WHERE t.request_id=r.request_id)" if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ibm_trial_email_notifications'").fetchone() else ''
    return db.execute('''SELECT r.request_id,r.service_id,c.consultation_id,c.finished_at,c.account_id,x.certificate_id,ac.contact_id,ac.email_encrypted
       FROM service_requests r JOIN consultations c USING(consultation_id) JOIN accounts a USING(account_id)
       JOIN reading_certificates x ON x.consultation_id=c.consultation_id
       JOIN account_contacts ac ON ac.account_id=c.account_id
       WHERE a.is_admin=1 AND a.status='active' AND c.status='completed' AND r.status='completed'
       AND ac.verified_at IS NOT NULL AND ac.revoked_at IS NULL
       AND x.certificate_id=(SELECT y.certificate_id FROM reading_certificates y WHERE y.consultation_id=c.consultation_id ORDER BY y.schema_version DESC LIMIT 1)
       '''+legacy_gate+'''
       AND NOT EXISTS(SELECT 1 FROM gnosis_completion_outbox o WHERE o.request_id=r.request_id)
       ORDER BY c.finished_at DESC''').fetchall()


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['status','recover','canary-list','canary-preview','canary-send']);p.add_argument('--request-id');p.add_argument('--retry-blocked',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args()
    settings=get_settings();need(settings.db_path==Path('/var/lib/gnosis/gnosis.sqlite3') and settings.data_dir==Path('/var/lib/gnosis') and settings.db_path.is_file(),'explicit_production_paths_required')
    with closing(connect(settings.db_path)) as db:
        if a.command=='status':
            print(json.dumps({'events':dict(db.execute('SELECT state,count(*) FROM reading_completion_events GROUP BY state').fetchall()),'mail':dict(db.execute('SELECT status,count(*) FROM gnosis_completion_outbox GROUP BY status').fetchall()),'blocked':[dict(r) for r in db.execute("SELECT request_id,attempts,last_error FROM reading_completion_events WHERE state='blocked'")],'email_enabled':os.environ.get('GNOSIS_ENABLE_COMPLETION_EMAIL')=='YES','event_enabled':enabled()},indent=2));return
        if a.command=='recover':
            need(a.apply and enabled(),'explicit_apply_and_event_flag_required')
            if a.retry_blocked:
                with processing_lock(settings.data_dir):
                    db.execute("UPDATE reading_completion_events SET state='pending',last_error=NULL,updated_at=? WHERE state='blocked'",(stamp(),))
            print(json.dumps(drain(db,settings.data_dir),indent=2));return
        if a.command=='canary-list':
            print(json.dumps([{'request_id':r['request_id'],'service':r['service_id'],'completed_at':r['finished_at'],'recipient':mask_email(decrypt_email(r['email_encrypted']))} for r in candidates(db)],indent=2));return
        need(enabled() and a.request_id,'explicit_request_and_event_flag_required')
        with processing_lock(settings.data_dir):
            row=next((r for r in candidates(db) if r['request_id']==a.request_id),None);need(row is not None,'canary_not_eligible_or_already_claimed')
            cert=db.execute('SELECT * FROM reading_certificates WHERE certificate_id=?',(row['certificate_id'],)).fetchone();need(verify_record(cert,settings.data_dir),'invalid_certificate')
            from gnosis_platform.certificate_api import validate_row
            validate_row(db,cert)
            message=prepared_message(cert,recipient=decrypt_email(row['email_encrypted']),sender=os.environ.get('GNOSIS_RESEND_FROM','quantum@gnosis.bot'),base_url=os.environ.get('GNOSIS_PUBLIC_BASE_URL','https://gnosis.bot'))
            if a.command=='canary-preview':
                print(json.dumps({'request_id':a.request_id,'recipient':mask_email(message['to'][0]),'subject':message['subject'],'text':message['text']},indent=2));return
            need(a.apply,'explicit_apply_required')
            # Do not turn on global mail delivery. Only this operator-selected admin reading.
            need(os.environ.get('GNOSIS_ENABLE_COMPLETION_EMAIL')!='YES','canary_requires_global_email_disabled')
            need(bool(os.environ.get('RESEND_API_KEY')) and bool(os.environ.get('GNOSIS_RESEND_FROM')),'missing_resend_configuration')
            db.execute('BEGIN IMMEDIATE')
            try:
                fresh=next((r for r in candidates(db) if r['request_id']==a.request_id),None);need(fresh is not None,'canary_already_claimed')
                db.execute('''INSERT INTO reading_completion_events(request_id,consultation_id,notify_requested,state,certificate_id,created_at,updated_at)
                   VALUES(?,?,1,'ready',?,?,?) ON CONFLICT(request_id) DO UPDATE SET notify_requested=1,state='ready',certificate_id=excluded.certificate_id,updated_at=excluded.updated_at''',(a.request_id,row['consultation_id'],row['certificate_id'],stamp(),stamp()))
                enqueue_after_settlement(db,request_id=a.request_id,consultation_id=row['consultation_id'],account_id=row['account_id']);suppress_legacy(db,a.request_id);db.commit()
            except Exception:db.rollback();raise
            os.environ['GNOSIS_ENABLE_COMPLETION_EMAIL']='YES'
            print(json.dumps(dispatch_one(db,request_id=a.request_id),indent=2))
if __name__=='__main__':main()
