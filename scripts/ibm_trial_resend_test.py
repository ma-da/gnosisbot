#!/usr/bin/env python3
"""Explicit API smoke test: sends ONE ordinary test email, no reading or credit changes."""
import argparse,json,os,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.ibm_trial_email import prepared_message,submit_resend
p=argparse.ArgumentParser()
p.add_argument('--send-real-email',action='store_true')
a=p.parse_args()
if not a.send_real_email or os.getenv('GNOSIS_ENABLE_TRIAL_EMAIL')!='YES':
    p.error('Requires --send-real-email and GNOSIS_ENABLE_TRIAL_EMAIL=YES')
recipient=os.environ['GNOSIS_TEST_NOTIFICATION_EMAIL']
sender=os.environ['GNOSIS_RESEND_FROM']
message=prepared_message(consultation_id='test',recipient=recipient,sender=sender,
    base_url=os.getenv('GNOSIS_PUBLIC_BASE_URL','https://gnosis.bot'))
message['subject']='Gnosis Resend connection test'
message['text']='This is a Gnosis notification API connection test. No quantum reading was submitted or charged.'
print(json.dumps({'sending_to':recipient,'subject':message['subject']}))
msg_id=submit_resend(api_key=os.environ['RESEND_API_KEY'],message=message,
                     idem_key='gnosis-resend-smoke-'+uuid4().hex)
print(json.dumps({'resend_message_id':msg_id,'status':'api_accepted'}))
