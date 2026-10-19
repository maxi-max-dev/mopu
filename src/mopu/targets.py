"""Exact targets resolved from a fresh accessibility read; no screen cache."""
import json
import re

FIELDS={'id','text','label','type'}
def validate_target(target):
    if not isinstance(target,dict) or not target or set(target)-FIELDS or not any(k in target for k in ('id','text','label')):
        raise ValueError('target需指定id/text/label，可附type；不支持索引或模糊匹配')
    if any(not isinstance(v,str) or not v.strip() or len(v)>500 for v in target.values()):
        raise ValueError('target字段需为1至500字')

def resolve_target(content,target):
    validate_target(target)
    found=[]
    for block in content:
        if block.get('type')!='text':continue
        for line in block.get('text','').splitlines():
            # Parse the complete backend line. Strings may themselves contain
            # bounds, attributes or the word disabled; never treat them as metadata.
            quoted = r'"(?:\\.|[^"\\])*"'
            attr = r'(?:text|label|name|value|id)=' + quoted
            row = re.fullmatch(
                r'@\S+ (\S+)((?: ' + attr + r')*) at=(-?\d+),(-?\d+) size=(\d+)x(\d+)'
                r'((?: (?:focused|selected|checked|disabled|\[(?:focused|selected|checked|disabled)\]))*)', line)
            if not row:continue
            fields={'type':row[1]}
            for m in re.finditer(r'(text|label|name|value|id)=(' + quoted + r')',row[2]):
                try:fields[m[1]]=json.loads(m[2])
                except ValueError:continue
            if not all(fields.get(k)==v for k,v in target.items()):continue
            # Ambiguous targets remain ambiguous even if one is disabled.
            if 'disabled' in row[7]:found.append(None);continue
            x,y,w,h=map(int,row.group(3,4,5,6))
            found.append({'x':x+w//2,'y':y+h//2} if min(x,y)>=0 and min(w,h)>0 else None)
    if len(found)!=1:return None,'target_missing' if not found else 'target_ambiguous'
    if found[0] is None:return None,'target_unavailable'
    return found[0],'target_matched'
