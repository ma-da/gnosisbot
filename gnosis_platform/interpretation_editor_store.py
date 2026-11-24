"""File-backed editorial workspace: immutable per-record revision history, corpus-wide release versions.

No SQLite operations. Publication uses a separate, guarded release coordinator.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile

from app.services import corpus as source

TRADITIONS=('classical','taoist','confucian')
TEXT_FIELDS=('title','essence','archetypal_meaning','historical_core','modern_meaning',
             'advice','shadow','reflection_question')
LINE_FIELDS=('interpretation','reflection')
# Special passages can include original source translations and Chinese evidence.
# Only these explicit synthetic/editorial keys are editable when found.
SPECIAL_FIELDS=set(TEXT_FIELDS)|set(LINE_FIELDS)
MAX_FIELD=20000
MAX_TOTAL=170000
MAX_REVISIONS=1000

class ConflictError(ValueError): pass
class DisabledError(RuntimeError): pass


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def digest(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,
              separators=(',',':')).encode('utf-8')).hexdigest()


def workspace():
    if os.getenv('GNOSIS_ENABLE_INTERPRETATION_EDITOR')!='1':
        raise DisabledError('Interpretation editor is not enabled')
    raw=os.getenv('GNOSIS_INTERPRETATION_EDITOR_DIR','')
    if not raw or not Path(raw).is_absolute():
        raise DisabledError('Dedicated absolute editor data directory must be configured')
    root=Path(raw).resolve()
    project=source.DATA.parent.parent.resolve()
    if root==project or root.is_relative_to(project):
        raise DisabledError('Drafts must be stored outside the application checkout')
    if root==Path('/') or not root.is_dir() or Path(raw).is_symlink():
        raise DisabledError('Editor data directory must already exist')
    if root.stat().st_mode & 0o007:
        raise DisabledError('Editor data directory must not grant access to other users')
    return root


def corpus():
    data=json.loads((source.DATA/'interpretations.json').read_bytes())
    source.validate_corpus(data)
    return data


def check_key(number,tradition):
    if type(number) is not int or not 1<=number<=64 or tradition not in TRADITIONS:
        raise ValueError('Invalid hexagram or tradition')


def original(number,tradition):
    check_key(number,tradition)
    root=corpus()
    rec=root['hexagrams'][number-1]
    return root,rec,rec[tradition]


def special_paths(value,prefix='special'):
    if not isinstance(value,dict):return []
    found=[]
    for k,v in value.items():
        # No arbitrary list paths or Chinese text/provenance fields.
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,50}',k):continue
        p=prefix+'.'+k
        if isinstance(v,dict):found.extend(special_paths(v,p))
        elif isinstance(v,str) and k in SPECIAL_FIELDS:found.append(p)
    return found


def path_value(obj,path):
    item=obj
    for key in path.split('.'):
        item=item[int(key)] if isinstance(item,list) else item[key]
    return item


def set_path(obj,path,value):
    parts=path.split('.');item=obj
    for key in parts[:-1]:item=item[int(key)] if isinstance(item,list) else item[key]
    item[int(parts[-1]) if isinstance(item,list) else parts[-1]]=value


def fields(original_obj,tradition):
    if tradition=='classical':return {}
    paths=[f for f in TEXT_FIELDS if f in original_obj and isinstance(original_obj[f],str)]
    for i,line in enumerate(original_obj['lines']):
        paths.extend('lines.'+str(i)+'.'+f for f in LINE_FIELDS if f in line and isinstance(line[f],str))
    paths.extend(special_paths(original_obj.get('special')))
    return {p:path_value(original_obj,p) for p in paths}


def validate_fields(obj,tradition,incoming):
    target=fields(obj,tradition)
    if not isinstance(incoming,dict) or incoming.keys()!=target.keys():
        raise ValueError('Editable field set changed; reload the editor')
    total=0
    for p,v in incoming.items():
        if not isinstance(v,str) or not v.strip():raise ValueError('All editable text fields must be nonempty: '+p)
        if len(v)>MAX_FIELD:raise ValueError('Field too long: '+p)
        if any(ord(c)<32 and c not in '\n\r\t' for c in v):raise ValueError('Invalid control character: '+p)
        total+=len(v)
    if total>MAX_TOTAL:raise ValueError('Record exceeds text size limit')
    # Verify the change remains compatible with the live corpus validator.
    sample=copy.deepcopy(obj)
    for p,v in incoming.items():set_path(sample,p,v)
    if [line['position'] for line in sample['lines']]!=list(range(1,7)):
        raise ValueError('Line positions may not be changed')
    return dict(incoming)


def state_path(root,number,tradition):
    check_key(number,tradition)
    return root/'records'/f'{number:02d}'/(tradition+'.json')


def blank(number,tradition,baseline):
    return {'version':1,'number':number,'tradition':tradition,'baseline_sha256':baseline,
            'head':None,'revisions':[],'reviewed_at':None,'reviewed_by':None,
            'approved_at':None,'approved_by':None,'events':[]}


def read_state(path,number,tradition,baseline):
    if not path.is_file():return blank(number,tradition,baseline)
    if path.is_symlink():raise ConflictError('Editor state symlink is not allowed')
    if path.stat().st_size>32_000_000:raise ConflictError('Editor state exceeds safety limit')
    s=json.loads(path.read_text('utf-8'))
    if s['number']!=number or s['tradition']!=tradition or s['version']!=1:
        raise ConflictError('Editor state identity mismatch')
    if s['baseline_sha256']!=baseline:
        raise ConflictError('Published corpus changed since draft was created; reconcile manually')
    return s


def baseline(rec,tradition,version):
    # Deliberately exclude the global corpus version: unrelated drafts survive
    # releases that update *other* records. Detect actual source changes instead.
    return digest({'tradition_content':rec[tradition],
                   'published_record_hash':rec.get('record_hashes',{}).get(tradition)})

def status(root,number,tradition,rec,version):
    path=state_path(root,number,tradition)
    base=baseline(rec,tradition,version)
    try:
        s=read_state(path,number,tradition,base)
        return {'head':s['head'],'reviewed_at':s['reviewed_at'],
                'approved_at':s['approved_at'],'revisions':len(s['revisions']),'stale':False}
    except ConflictError:
        return {'head':None,'reviewed_at':None,'approved_at':None,'revisions':0,'stale':True}


def catalog(query=''):
    root=workspace(); d=corpus(); result=[]; q=query.casefold().strip()
    for r in d['hexagrams']:
        if q:
            texts=[r.get('chinese',''),r.get('pinyin',''),str(r['number']),
                   r['taoist'].get('title',''),r['confucian'].get('title',''),r.get('name','')]
            for t in ('taoist','confucian'):
                a=r[t]
                texts.extend(a.get(k,'') for k in TEXT_FIELDS)
                texts.extend(x.get('interpretation','')+' '+x.get('reflection','') for x in a['lines'])
                texts.extend(str(x) for x in a.get('themes',[]))
            if q not in ' '.join(str(x) for x in texts).casefold():continue
        result.append({'number':r['number'],'symbol':r['symbol'],'chinese':r['chinese'],
                       'pinyin':r['pinyin'],'title':r['taoist'].get('title') or r.get('name'),
                       'traditions':{t:status(root,r['number'],t,r,d['corpus_version']) for t in TRADITIONS},
                       'published_approval':dict(r['human_approved'])})
    progress={t:{'approved':0,'reviewed':0,'drafted':0,'stale':0,'published_approved':0} for t in TRADITIONS}
    for r in d['hexagrams']:
        for t in TRADITIONS:
            s=status(root,r['number'],t,r,d['corpus_version']);p=progress[t]
            p['approved']+=int(bool(s['approved_at']))
            p['reviewed']+=int(bool(s['reviewed_at']))
            p['drafted']+=int(bool(s['head']))
            p['stale']+=int(s['stale'])
            p['published_approved']+=int(bool(r['human_approved'].get(t)))
    return {'hexagrams':result,'progress':progress,'total_records':192,
            'corpus_version':d['corpus_version'],'publication_enabled':False}


def get_record(number,tradition):
    root=workspace(); c,rec,obj=original(number,tradition)
    s=read_state(state_path(root,number,tradition),number,tradition,baseline(rec,tradition,c['corpus_version']))
    originals=fields(obj,tradition)
    current=s['revisions'][-1]['fields'] if s['revisions'] else originals
    return {'number':number,'tradition':tradition,'record':rec, 'editable_original':originals,
            'editable_current':current,'revision':s['head'],
            'reviewed_at':s['reviewed_at'],'reviewed_by':s['reviewed_by'],
            'approved_at':s['approved_at'],'approved_by':s['approved_by'],
            'history':[{'id':v['id'],'actor':v['actor'],'at':v['at'],'action':v['action'],
                        'changed_fields':v['changed_fields']} for v in reversed(s['revisions'])],
            'events':list(reversed(s['events'][-50:])),
            'published_approved':bool(rec['human_approved'][tradition]),
            'publication_enabled':False,'corpus_version':c['corpus_version']}


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=path.with_suffix('.lock')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a+') as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)


def atomic_json(path,state):
    data=(json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode('utf-8')
    if len(data)>31_000_000:raise ValueError('Editorial history at capacity; archive required')
    if path.is_file():
        # Keep a byte-exact, per-mutation recovery copy outside the live state file.
        recovery=path.parent/'backups'
        recovery.mkdir(mode=0o700,exist_ok=True)
        snapshot=recovery/(path.stem+'-'+uuid4().hex+'.json')
        with path.open('rb') as src, snapshot.open('xb') as dst:
            os.chmod(snapshot,0o600)
            shutil.copyfileobj(src,dst)
            dst.flush();os.fsync(dst.fileno())
    fd,tmp=tempfile.mkstemp(prefix='.editor-',dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        dirfd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(dirfd)
        finally:os.close(dirfd)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def event(s,action,actor,**extra):
    s['events'].append({'id':uuid4().hex,'at':utc(),'actor':actor,'action':action,**extra})


@contextmanager
def publication_lock(root, *, exclusive):
    fd=os.open(root/'.publication.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a+') as file:
        fcntl.flock(file,fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:yield
        finally:fcntl.flock(file,fcntl.LOCK_UN)


def mutate(number,tradition,actor,action,expected_head,*,incoming=None,revision_id=None):
    root=workspace()
    with publication_lock(root,exclusive=False):
        return _mutate(number,tradition,actor,action,expected_head,incoming=incoming,revision_id=revision_id)


def _mutate(number,tradition,actor,action,expected_head,*,incoming=None,revision_id=None):
    if not isinstance(actor,str) or not re.fullmatch('[0-9a-f]{64}',actor):
        raise ValueError('Invalid administrator identity')
    root=workspace(); c,rec,obj=original(number,tradition)
    path=state_path(root,number,tradition)
    with locked(path):
        s=read_state(path,number,tradition,baseline(rec,tradition,c['corpus_version']))
        if expected_head!=s['head']:
            raise ConflictError('This record changed in another session; reload before saving')
        if action=='save':
            if tradition=='classical':raise ValueError('Classical source material is read-only')
            values=validate_fields(obj,tradition,incoming)
            if len(s['revisions'])>=MAX_REVISIONS:raise ValueError('Revision limit reached')
            previous=s['revisions'][-1]['fields'] if s['revisions'] else fields(obj,tradition)
            changed=[k for k in values if values[k]!=previous[k]]
            if not changed:return {'changed':False,'revision':s['head']}
            rev={'id':uuid4().hex,'at':utc(),'actor':actor,'action':'save',
                 'changed_fields':changed,'fields':values}
            s['head']=rev['id'];s['revisions'].append(rev)
            s['reviewed_at']=s['reviewed_by']=s['approved_at']=s['approved_by']=None
            event(s,'save',actor,revision=rev['id'],changed_fields=changed,
                  previous_sha256=digest(previous),new_sha256=digest(values))
        elif action=='restore':
            if tradition=='classical':raise ValueError('Classical source material is read-only')
            previous_revision=next((x for x in s['revisions'] if x['id']==revision_id),None)
            if previous_revision is None:raise ValueError('Unknown historical revision')
            if len(s['revisions'])>=MAX_REVISIONS:raise ValueError('Revision limit reached')
            values=previous_revision['fields']
            previous=s['revisions'][-1]['fields']
            rev={'id':uuid4().hex,'at':utc(),'actor':actor,'action':'restore',
                 'changed_fields':[k for k in values if values[k]!=previous[k]],'fields':values}
            s['head']=rev['id'];s['revisions'].append(rev)
            s['reviewed_at']=s['reviewed_by']=s['approved_at']=s['approved_by']=None
            event(s,'restore',actor,revision=rev['id'],restored_from=revision_id,
                  previous_sha256=digest(previous),new_sha256=digest(values))
        elif action=='review':
            s['reviewed_at']=utc();s['reviewed_by']=actor
            s['approved_at']=s['approved_by']=None
            event(s,'review',actor,revision=s['head'])
        elif action=='approve':
            if not s['reviewed_at']:raise ValueError('Review the record before approval')
            s['approved_at']=utc();s['approved_by']=actor
            event(s,'approve',actor,revision=s['head'])
        elif action=='unapprove':
            s['approved_at']=s['approved_by']=None
            event(s,'unapprove',actor,revision=s['head'])
        elif action=='unreview':
            s['reviewed_at']=s['reviewed_by']=s['approved_at']=s['approved_by']=None
            event(s,'unreview',actor,revision=s['head'])
        else:raise ValueError('Unsupported editorial action')
        atomic_json(path,s)
        return {'changed':True,'revision':s['head'],'reviewed_at':s['reviewed_at'],
                'approved_at':s['approved_at']}


def history_revision(number,tradition,revision_id):
    root=workspace();c,rec,obj=original(number,tradition)
    s=read_state(state_path(root,number,tradition),number,tradition,baseline(rec,tradition,c['corpus_version']))
    match=next((x for x in s['revisions'] if x['id']==revision_id),None)
    if match is None:raise ValueError('Revision not found')
    return match
