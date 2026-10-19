"""Install this portable OpenClaw adapter, preserving config and earlier files."""
import argparse
import datetime
import json
import shutil
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--openclaw-home',type=Path,default=Path.home()/'.openclaw')
    p.add_argument('--state',type=Path,default=(Path.home()/'.local/share/phone-harness' if (Path.home()/'.local/share/phone-harness').exists() else Path.home()/'.local/share/mopu'))
    p.add_argument('--agent',default='main');p.add_argument('--name',default='Jarvis')
    args=p.parse_args(); root=args.openclaw_home.expanduser().resolve()
    config=root/'openclaw.json'; original=config.read_bytes(); obj=json.loads(original)
    agent=next((a for a in obj.get('agents',{}).get('list',[]) if a.get('id')==args.agent),None)
    if not agent: p.error('Choose an existing OpenClaw agent ID; no new AI agent will be created.')
    if not (args.state/'config.json').exists(): p.error('Run Mopu setup first.')
    stamp=datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')
    backup=args.state/'backups'/('openclaw-'+stamp); backup.mkdir(parents=True,mode=0o700)
    (backup/'openclaw.json').write_bytes(original);(backup/'openclaw.json').chmod(0o600)
    target=root/'extensions/phone-harness'
    if target.exists(): shutil.copytree(target,backup/'previous-plugin')
    source=Path(__file__).parent
    shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    plugins=obj.setdefault('plugins',{})
    if 'allow' in plugins and 'phone-harness' not in plugins['allow']:plugins['allow'].append('phone-harness')
    plugins.setdefault('entries',{})['phone-harness']={'enabled':True,'config':{'stateDir':str(args.state.resolve()),'allowedAgents':[args.agent],'displayName':args.name,'resumeOnRelease':True}}
    # Do not replace any existing allowlist/denylist/model/provider settings.
    tool_config=agent.setdefault('tools',{})
    if 'allow' in tool_config:
        for t in json.loads((source/'tools.json').read_text()):
            if t['name'] not in tool_config['allow']:tool_config['allow'].append(t['name'])
    if config.read_bytes()!=original: raise RuntimeError('OpenClaw configuration changed concurrently; preserved it. Rerun after review.')
    temp=config.with_suffix('.phone-new');temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');temp.chmod(0o600);temp.replace(config)
    assert json.loads(config.read_text())==obj
    print('Installed Mopu for '+args.agent+'. Backups preserved in '+str(backup))
    print('Run openclaw config validate. Start a new turn in the intended conversation; do not switch conversations to resume a queued phone task.')

if __name__=='__main__':main()
