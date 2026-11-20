"""Local provisioning utility. Never generates or stores private account keys."""
import argparse
import csv
import os
import secrets
from pathlib import Path
from uuid import uuid4
from .db import connect, migrate
from .identity import create_invitation,grant

def main():
    p=argparse.ArgumentParser(description='Local Gnosis provisioning (protect access to this shell and database)')
    sub=p.add_subparsers(dest='action',required=True)
    invitations=sub.add_parser('invitations',help='Issue single-use invitation tokens')
    invitations.add_argument('--count',type=int,required=True)
    invitations.add_argument('--group',required=True)
    invitations.add_argument('--credits',type=int,required=True)
    invitations.add_argument('--days',type=int,default=14)
    invitations.add_argument('--output',type=Path,required=True)
    grantp=sub.add_parser('grant',help='Grant credits with audit record')
    grantp.add_argument('--account-id',required=True)
    grantp.add_argument('--credits',type=int,required=True)
    grantp.add_argument('--reason',required=True)
    grantp.add_argument('--idempotency-key',required=True)
    admin=sub.add_parser('make-admin',help='Explicitly grant administrator privileges')
    admin.add_argument('--account-id',required=True)
    args=p.parse_args()
    with connect() as db:
        migrate(db)
        if args.action=='invitations':
            if not 1 <= args.count <= 100:
                p.error('Count must be 1..100')
            if args.output.exists():
                p.error('Output already exists; refusing overwrite')
            # Save token file with owner-only permissions, outside public tree.
            path=args.output.expanduser().resolve()
            if any(folder in path.parts for folder in ('static','public','www')):
                p.error('Invitation tokens must not be saved in site/public directories')
            path.parent.mkdir(parents=True,exist_ok=True)
            fd=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:
                    writer=csv.writer(stream)
                    writer.writerow(['invitation_token','group','credits','expires_days'])
                    for _ in range(args.count):
                        writer.writerow([create_invitation(db,args.group,args.credits,args.days),args.group,args.credits,args.days])
            except Exception:
                path.unlink(missing_ok=True)
                raise
            print(f'Created {args.count} invitations in {path} (owner-only; keep private)')
        elif args.action=='grant':
            created=grant(db,args.account_id,args.credits,'local_admin',args.reason,args.idempotency_key)
            print('Credit grant:', 'created' if created else 'already applied')
        elif args.action=='make-admin':
            if os.environ.get('GNOSIS_PROVISION_ADMIN')!='YES':
                p.error('Set GNOSIS_PROVISION_ADMIN=YES for this one invocation')
            account=db.execute('UPDATE accounts SET is_admin=1 WHERE account_id=? AND status=\'active\'',(args.account_id,))
            if account.rowcount != 1:
                p.error('No active account found')
            print('Administrator enabled for:',args.account_id)

if __name__=='__main__':main()
