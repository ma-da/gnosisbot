#!/usr/bin/env python3
"""Verify an exact SHA256 OTS proof against two mainnet explorer block headers.
Run with the existing OpenTimestamps venv. No calendar queries or wallet access.
Explorer agreement is a trust assumption, not full-chain validation.
"""
import hashlib, json, re, sys
from pathlib import Path
from urllib.request import Request, urlopen

BASES=('https://mempool.space/api','https://blockstream.info/api')

def get(base,path):
    with urlopen(Request(base+path,headers={'User-Agent':'Gnosis-GQTP/1.0','Accept':'text/plain, application/json'}),timeout=8) as r:
        data=r.read(4097)
    if len(data)>4096:raise ValueError('Explorer response too large')
    return data.decode('ascii').strip()

def header_hash(header):
    return hashlib.sha256(hashlib.sha256(header).digest()).digest()[::-1].hex()

def verify_header(header,blockhash,root):
    if len(header)!=80 or header_hash(header)!=blockhash or header[36:68]!=root:return False
    bits=int.from_bytes(header[72:76],'little');exp=bits>>24;mant=bits&0x007fffff
    if bits&0x00800000 or not mant or not 3<=exp<=32:return False
    target=mant<<(8*(exp-3))
    return target<=0xFFFF<<(8*(0x1D-3)) and int(blockhash,16)<=target

def verify_paths(paths,fetch=get):
    # at least one complete matching path; both explorers must agree at its height.
    for height,root in sorted(set(paths),key=lambda x:x[0])[:8]:
        if type(height) is not int or not 1<=height<=2**32-1 or len(root)!=32:continue
        results=[]
        try:
            for base in BASES:
                tip=int(fetch(base,'/blocks/tip/height'))
                h=fetch(base,f'/block-height/{height}')
                if not re.fullmatch(r'[0-9a-f]{64}',h) or tip-height+1<6:break
                header=bytes.fromhex(fetch(base,f'/block/{h}/header'))
                if not verify_header(header,h,root):break
                results.append((h,header,tip-height+1))
            if len(results)==2 and results[0][:2]==results[1][:2]:
                return {'height':height,'block_hash':results[0][0],'merkle_root':root[::-1].hex(),'confirmations_min':min(r[2] for r in results),'sources':list(BASES)}
        except (OSError,ValueError,TimeoutError):continue
    return None

def read_paths(checkpoint,proof):
    from opentimestamps.core.timestamp import DetachedTimestampFile
    from opentimestamps.core.serialize import BytesDeserializationContext
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    detached=DetachedTimestampFile.deserialize(BytesDeserializationContext(proof))
    if type(detached.file_hash_op) is not OpSHA256 or detached.file_digest!=hashlib.sha256(checkpoint).digest():raise ValueError('Checkpoint digest differs from proof')
    return [(att.height,msg) for msg,att in detached.timestamp.all_attestations() if type(att) is BitcoinBlockHeaderAttestation]

def main():
    if len(sys.argv)!=3:raise SystemExit('Usage: gqtp_verify_explorers.py CHECKPOINT PROOF')
    cp,p=map(Path,sys.argv[1:]); result=verify_paths(read_paths(cp.read_bytes(),p.read_bytes()))
    print(json.dumps(result or {'status':'not_verified'}));return 0 if result else 1

if __name__=='__main__':sys.exit(main())
