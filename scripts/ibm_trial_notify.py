#!/usr/bin/env python3
"""Send one administrator-controlled Resend completion notification after settlement."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gnosis_platform.db import connect
from gnosis_platform.ibm_trial_email import send_completed_trial
p=argparse.ArgumentParser()
p.add_argument('request_id',help='32-character hexadecimal service request ID')
a=p.parse_args()
if len(a.request_id)!=32 or any(c not in '0123456789abcdef' for c in a.request_id):
    p.error('Expected a 32-character hexadecimal request ID')
with connect() as db:
    result=send_completed_trial(db,a.request_id)
print(json.dumps(result,indent=2))
