"""Single-action versioned derivative corpus publisher.

Publishes the entire site corpus as a new semantic version, never independently
versions hexagrams. Does not change canonical research source hashes or use SQLite.
Preserve inherited research record hashes unchanged. Publish a separately
verifiable whole-site editorial edition without claiming research was rebuilt.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from uuid import uuid4

from app.services import corpus as source
from . import interpretation_editor_store as store


def sha(data): return hashlib.sha256(data).hexdigest()
def json_bytes(obj): return (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf8')


def _files():
    return source.DATA/'interpretations.json',source.DATA/'interpretation_manifest.json'


def _load_verified():
    cp,mp=_files(); raw=cp.read_bytes(); meta_raw=mp.read_bytes()
    data=json.loads(raw); manifest=json.loads(meta_raw)
    source.validate_corpus(data)
    if manifest['files']['site/interpretations.json'] != sha(raw):
        raise store.ConflictError('The site corpus SHA-256 differs from the current release manifest')
    if manifest['files']['site/hexagrams_catalog.json'] != sha(source.serialize_catalog(data['hexagrams'])):
        raise store.ConflictError('The site catalog SHA-256 differs from the release manifest')
    if any(manifest['metadata'][k] != data[k] for k in ('corpus_version','schema_version','status','records_total','human_approved_records')):
        raise store.ConflictError('Corpus and manifest metadata disagree')
    _check_derivative_integrity(data,manifest)
    return data,manifest,raw,meta_raw


def _next_version(v):
    parts=[int(x) for x in v.split('.')]
    if len(parts)!=3 or any(n<0 or n>99999 for n in parts):raise ValueError('Unsupported version')
    return '%d.%d.%d'%(parts[0],parts[1],parts[2]+1)


# The inherited record_hashes are research provenance references, not necessarily
# the checksum of the materialized website tradition object. The LIVE base
# manifest attests to the complete website payload. For every editorial release,
# add an independent, checked site-content digest for EACH tradition. Never
# relabel or overwrite an inherited research provenance hash.
CONTENT_HASH_SCHEME='sha256-json-sorted-compact-utf8-v1'

def _source_hash_fingerprint(data):
    return source.digest([{'number':r['number'], 'record_hashes':r['record_hashes']}
                          for r in data['hexagrams']])

def _site_hashes(data):
    return {str(r['number']):{t:source.digest(r[t]) for t in store.TRADITIONS}
            for r in data['hexagrams']}

def _check_derivative_integrity(data, manifest):
    """Verify inherited research lineage and all site hashes on derivative releases.

    For the original non-editorial release, the authoritative original manifest
    already verifies the exact whole-corpus bytes and generated catalog bytes.
    The original source hash algorithm is not asserted or guessed.
    """
    inherited=_source_hash_fingerprint(data)
    release=manifest.get('editorial_release')
    if release is not None:
        if not isinstance(release,dict) or release.get('type')!='site_editorial_derivative':
            raise store.ConflictError('Unknown editorial release metadata')
        if release.get('source_record_hashes_sha256') != inherited:
            raise store.ConflictError('Inherited source record hashes changed unexpectedly')
        if release.get('site_content_hash_scheme') != CONTENT_HASH_SCHEME:
            raise store.ConflictError('Unrecognized editorial site content hash scheme')
        if release.get('site_content_hashes') != _site_hashes(data):
            raise store.ConflictError('Editorial site tradition checksum mismatch')
        if release.get('source_research_hashes_unchanged') is not True:
            raise store.ConflictError('Source provenance continuity not recorded')
    # Diagnostic only; a nonmatch is not corruption of a validated base release.
    original_match_count=sum(source.digest(r[t])==r['record_hashes'][t]
                             for r in data['hexagrams'] for t in store.TRADITIONS)
    return original_match_count,inherited


def _saferead_state(root,number,t,rec,version):
    base=store.baseline(rec,t,version)
    return store.read_state(store.state_path(root,number,t),number,t,base)


def _compose(data,root):
    result=copy.deepcopy(data)
    diffs=[]; approved_delta=[]; pending=0; updated_states={}
    for row in result['hexagrams']:
        origin=data['hexagrams'][row['number']-1]
        for t in store.TRADITIONS:
            s=_saferead_state(root,row['number'],t,origin,data['corpus_version'])
            if s['head'] and not s['approved_at']:pending+=1
            if not s['approved_at']:
                continue
            if not s['reviewed_at'] or not s['approved_by']:
                raise store.ConflictError('Unreviewed approval record: %d/%s'%(row['number'],t))
            if t!='classical' and s['revisions']:
                current=store.fields(origin[t],t)
                values=store.validate_fields(origin[t],t,s['revisions'][-1]['fields'])
                changes=[]
                for field,new in values.items():
                    old=current[field]
                    if new!=old:
                        changes.append({'number':row['number'],'tradition':t,
                            'field':field,'before':old,'after':new,'approved_by':s['approved_by']})
                        store.set_path(row[t],field,new)
                        if t=='taoist' and field in ('title','modern_meaning','historical_core','advice','shadow','reflection_question'):
                            # title and name are independent legacy labels in
                            # the LIVE 0.9.0 data (0/64 title and name mirrors).
                            # Mirror only fields that actually matched their
                            # Taoist source. Do not overwrite independent labels.
                            mirrors=['title','name'] if field=='title' else [field]
                            for key in mirrors:
                                if key in row and key in origin and origin[key]==old:
                                    row[key]=new
                                elif field!='title' and key in row:
                                    raise store.ConflictError('Taoist root mirror drift: %d/%s'%(row['number'],key))
                diffs.extend(changes)
                if changes:
                    # record_hashes are inherited SOURCE references, not a
                    # site-content checksum. Per-release site hashes go in
                    # editorial_release.site_content_hashes instead.
                    updated_states[(row['number'],t)]=s
            if not row['human_approved'][t]:
                row['human_approved'][t]=True
                approved_delta.append({'number':row['number'],'tradition':t,'approved_by':s['approved_by']})
    result['human_approved_records']=sum(sum(row['human_approved'].values()) for row in result['hexagrams'])
    return result,diffs,approved_delta,pending,updated_states


def _site_directory_writable():
    """Check both DAC permissions and systemd/OS read-only mount state.

    os.access alone incorrectly reports writable paths under ProtectSystem
    when the directory is remounted read-only inside the service namespace.
    This check is read-only; preview never creates files inside app/data.
    """
    try:
        d=source.DATA
        return (d.is_dir() and os.access(d,os.W_OK) and
                not (os.statvfs(d).f_flag & getattr(os,'ST_RDONLY',1)))
    except OSError:
        return False


def _candidate():
    root=store.workspace()
    data,manifest,before_raw,manifest_before=_load_verified()
    legacy_hash_matches,source_hash_fingerprint=_check_derivative_integrity(data,manifest)
    result,diffs,approved_delta,pending,states=_compose(data,root)
    if _source_hash_fingerprint(result)!=source_hash_fingerprint:
        raise store.ConflictError('Editorial composition changed inherited source hashes')
    changed=bool(diffs or approved_delta)
    if changed:
        new_version=_next_version(data['corpus_version'])
        result['corpus_version']=new_version
        for row in result['hexagrams']:row['corpus_version']=new_version
        source.validate_corpus(result)
    else:new_version=data['corpus_version']
    reasons=[]
    if not changed:reasons.append('No newly approved editorial changes to publish')
    if not _site_directory_writable():
        reasons.append('Corpus directory is not writable in the API service sandbox; verify explicit ReadWritePaths and Unix permissions before enabling publication')
    if os.getenv('GNOSIS_INTERPRETATION_PUBLIC_FRONTEND_REVIEWED')!='YES':
        reasons.append('Public traditions explorer escaping audit has not been acknowledged; publishing is disabled')
    publication_dir=root/'publications'
    if publication_dir.is_dir():
        unresolved=[]
        for log in publication_dir.glob('*.json'):
            if log.is_symlink():continue
            try:
                if json.loads(log.read_text('utf8')).get('status')=='preparing':unresolved.append(log.stem)
            except (ValueError,OSError):
                unresolved.append(log.stem)
        if unresolved:
            reasons.append('An unfinished publication event requires inspection and recovery before another release')
    return dict(root=root,data=data,manifest=manifest,before_raw=before_raw,manifest_before=manifest_before,
        updated=result,diffs=diffs,approvals=approved_delta,pending=pending,states=states,
        legacy_hash_matches=legacy_hash_matches,source_hash_fingerprint=source_hash_fingerprint,
        version_before=data['corpus_version'],version_after=new_version,
        before_sha256=sha(before_raw),changed=changed, reasons=reasons)


def _prepare(c,actor,*,created=None):
    m=copy.deepcopy(c['manifest']);version=c['version_after'];created=created or store.utc()
    d=c['updated'];d['status']=c['data']['status']
    for row in d['hexagrams']:row['editorial_status']=d['status']
    corpus_bytes=json_bytes(d);catalog=source.serialize_catalog(d['hexagrams'])
    m['metadata']['corpus_version']=version
    m['metadata']['human_approved_records']=d['human_approved_records']
    m['files']['site/interpretations.json']=sha(corpus_bytes)
    m['files']['site/hexagrams_catalog.json']=sha(catalog)
    # The 192 inherited source references stay byte-for-byte intact.
    # These NEW values describe the complete rendered website edition, using a
    # documented algorithm whose result is verifiable on every subsequent load.
    m['editorial_release']={
        'type':'site_editorial_derivative','source_research_hashes_unchanged':True,
        'source_record_hashes_sha256':c['source_hash_fingerprint'],
        'source_hashes_semantics':'inherited pre-editorial references; original generator not independently verified',
        'research_master_rebuilt':False,
        'site_content_hash_scheme':CONTENT_HASH_SCHEME,
        'site_content_hashes':_site_hashes(d),
        'parent_corpus_version':c['version_before'],'parent_site_sha256':c['before_sha256'],
        'published_utc':created,'published_by_admin':actor,
        'changed_fields':len(c['diffs']),'newly_approved_records':len(c['approvals'])}
    manifest_bytes=json_bytes(m)
    return corpus_bytes,catalog,manifest_bytes


def _inspect_release(corpus_bytes,catalog,manifest_bytes,root):
    # Use the actual established validation rather than a parallel imitation.
    import importlib.util
    script=source.DATA.parents[1]/'scripts/update_corpus.py'
    spec=importlib.util.spec_from_file_location('gnosis_update_corpus_validation',script)
    if spec is None or spec.loader is None:raise RuntimeError('Cannot load release validator')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='corpus-preflight-',dir=root) as name:
        p=Path(name);site=p/'site';site.mkdir()
        (site/'interpretations.json').write_bytes(corpus_bytes)
        (site/'hexagrams_catalog.json').write_bytes(catalog)
        (p/'release_manifest.json').write_bytes(manifest_bytes)
        module.inspect_release(p)


def _preview_locked():
    c=_candidate();actor='0'*64
    if c['changed']:
        a,b,d=_prepare(c,actor)
        _inspect_release(a,b,d,c['root'])
        c['after_sha256']=sha(a)
    else:c['after_sha256']=None
    return c


def preview():
    root=store.workspace()
    with store.publication_lock(root,exclusive=False):
        c=_preview_locked()
    return {'enabled':os.getenv('GNOSIS_ENABLE_INTERPRETATION_PUBLICATION')=='YES',
      'can_publish':not c['reasons'], 'reasons':c['reasons'],
      'version_before':c['version_before'],'version_after':c['version_after'],
      'before_sha256':c['before_sha256'],'after_sha256':c['after_sha256'],
      'plan_token':sha(json_bytes({'before':c['before_sha256'],'after':c['after_sha256'],
                 'diffs':c['diffs'],'approvals':c['approvals']})),
      'changed_fields':len(c['diffs']),'changed_records':len(set((x['number'],x['tradition']) for x in c['diffs'])),
      'new_approvals':len(c['approvals']),'unapproved_drafts_excluded':c['pending'],
      'hash_matches':c['legacy_hash_matches'],
      'hash_basis':'Legacy hashes preserved unchanged; new website-content hashes use sorted compact JSON',
      'source_hashes_sha256':c['source_hash_fingerprint'],
      'diff_summary':[{'number':x['number'],'tradition':x['tradition'],'field':x['field'],
                       'before_sha256':sha(x['before'].encode()),'after_sha256':sha(x['after'].encode())}
                      for x in c['diffs'][:100]],
      'latest_publications':history(limit=10, locked=True)}


def _fsyncdir(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def _atomic_bytes(p,b):
    fd,name=tempfile.mkstemp(prefix='.release-',dir=p.parent)
    try:
        os.fchmod(fd,0o644)
        with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
        os.replace(name,p);_fsyncdir(p.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def history(limit=20,*,locked=False):
    root=store.workspace();path=root/'publications';result=[]
    if path.is_dir():
        for f in sorted(path.glob('*.json'),reverse=True)[:limit]:
            if f.is_symlink():continue
            d=json.loads(f.read_text())
            result.append({'release_id':f.stem,**{k:d.get(k) for k in ('published_utc','actor','version_before','version_after',
                          'before_sha256','after_sha256','changed_fields','changed_records','newly_approved_records','status')}})
    return result


def history_detail(release_id):
    if not isinstance(release_id,str) or not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{12}',release_id):
        raise ValueError('Invalid release identifier')
    path=store.workspace()/'publications'/(release_id+'.json')
    if not path.is_file() or path.is_symlink():raise ValueError('Unknown release')
    data=json.loads(path.read_text('utf8'))
    return {'release_id':release_id,'published_utc':data.get('published_utc'),
            'actor':data.get('actor'),'status':data.get('status'),
            'version_before':data.get('version_before'),'version_after':data.get('version_after'),
            'before_sha256':data.get('before_sha256'),'after_sha256':data.get('after_sha256'),
            'field_changes':data.get('field_changes',[]),'approval_changes':data.get('approval_changes',[])}


def publish(*,actor,expected_token):
    if os.getenv('GNOSIS_ENABLE_INTERPRETATION_PUBLICATION')!='YES':
        raise store.DisabledError('Corpus publishing is disabled in server configuration')
    if not re.fullmatch('[0-9a-f]{64}',actor):raise ValueError('Invalid admin actor')
    if not re.fullmatch('[0-9a-f]{64}',expected_token or ''):raise ValueError('Invalid publication token')
    root=store.workspace()
    with store.publication_lock(root,exclusive=True):
        c=_preview_locked()
        token=sha(json_bytes({'before':c['before_sha256'],'after':c['after_sha256'],
                             'diffs':c['diffs'],'approvals':c['approvals']}))
        if token!=expected_token:raise store.ConflictError('Editorial plan changed; refresh publication preview')
        if c['reasons']:raise ValueError('Publication preflight failed: '+'; '.join(c['reasons']))
        when=store.utc()
        content,catalog,manifest=_prepare(c,actor,created=when)
        _inspect_release(content,catalog,manifest,root)
        cp,mp=_files()
        if cp.read_bytes()!=c['before_raw'] or mp.read_bytes()!=c['manifest_before']:
            raise store.ConflictError('Another corpus publication occurred; refresh and retry')
        time_key=when.replace(':','').replace('-','').replace('.','')
        release_id=time_key+'-'+uuid4().hex[:12]
        backups=root/'release-backups'/release_id;backups.mkdir(parents=True,mode=0o700)
        os.chmod(backups,0o700)
        for name,b in (('interpretations.json',c['before_raw']),('interpretation_manifest.json',c['manifest_before'])):
            p=backups/name;p.write_bytes(b);p.chmod(0o600)
        for name,b in (('new-interpretations.json',content),('new-interpretation_manifest.json',manifest),('new-hexagrams_catalog.json',catalog)):
            p=backups/name;p.write_bytes(b);p.chmod(0o600)
        _fsyncdir(backups)
        # A pending immutable event survives a crash. It is not presented as a success.
        logdir=root/'publications';logdir.mkdir(parents=True,exist_ok=True,mode=0o700)
        log=logdir/(release_id+'.json')
        event={'status':'preparing','published_utc':when,'actor':actor,
          'version_before':c['version_before'],'version_after':c['version_after'],
          'before_sha256':c['before_sha256'],'after_sha256':sha(content),
          'manifest_before_sha256':sha(c['manifest_before']),'manifest_after_sha256':sha(manifest),
          'changed_fields':len(c['diffs']),
          'changed_records':len(set((x['number'],x['tradition']) for x in c['diffs'])),
          'newly_approved_records':len(c['approvals']),'excluded_unapproved_drafts':c['pending'],
          'field_changes':c['diffs'],'approval_changes':c['approvals'],
          'backups':str(backups),'release_type':'site_editorial_derivative'}
        store.atomic_json(log,event)
        state_before={store.state_path(root,n,t):store.state_path(root,n,t).read_bytes()
                      for n,t in c['states']}
        try:
            _atomic_bytes(cp,content)
            _atomic_bytes(mp,manifest)
            # The full package must be exactly verifiable after installation.
            active,meta,raw,metaraw=_load_verified()
            if sha(raw)!=sha(content) or sha(metaraw)!=sha(manifest):
                raise store.ConflictError('Installed release verification failed')
            # Keep ongoing private history, but rebase published active drafts to the
            # newly current corpus; independent unapproved drafts retain old content.
            for (n,t),s in c['states'].items():
                p=store.state_path(root,n,t)
                rec=active['hexagrams'][n-1]
                s['baseline_sha256']=store.baseline(rec,t,active['corpus_version'])
                store.event(s,'published',actor,corpus_version=active['corpus_version'],release=release_id)
                store.atomic_json(p,s)
            event['status']='active'
            store.atomic_json(log,event)
        except BaseException:
            # If the process stays alive, restore both files. A power loss is
            # detected from the durable 'preparing' publication event.
            _atomic_bytes(cp,c['before_raw']);_atomic_bytes(mp,c['manifest_before'])
            for path,prior_bytes in state_before.items():_atomic_bytes(path,prior_bytes)
            try:store.atomic_json(log,{**event,'status':'rolled_back_after_error'})
            except Exception:pass
            raise
        return {'status':'active','version':c['version_after'],
                'previous_version':c['version_before'], 'published_utc':when,
                'before_sha256':c['before_sha256'],'after_sha256':sha(content),
                'changed_fields':len(c['diffs']),'new_approvals':len(c['approvals']),
                'release_id':release_id,
                'note':'Public interpretation and demo caches refresh per file version; historical receipts are unchanged'}
