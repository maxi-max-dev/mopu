"""Explicit first-use setup and non-invasive diagnostics. Never navigates Android."""
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

SCRCPY_URL = 'https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/scrcpy-server-v5.0.1'
SCRCPY_SHA = '764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536'


def executable(name, supplied=None):
    if supplied:
        candidate=Path(supplied).expanduser()
        if candidate.is_file() and os.access(candidate,os.X_OK): return str(candidate.absolute())
        raise RuntimeError(f'The configured {name} executable is missing or not executable; correct its path.')
    found = supplied or shutil.which(name)
    candidates = [found] if found else []
    candidates += ['/opt/homebrew/bin/'+name, '/usr/local/bin/'+name]
    if name == 'adb': candidates += [str(Path.home()/'Library/Android/sdk/platform-tools/adb'),str(Path.home()/'Android/Sdk/platform-tools/adb')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate,os.X_OK): return str(Path(candidate).absolute())
    raise RuntimeError(f'{name} is missing. Install it from its official project and rerun setup; no phone settings were changed.')


def devices(adb):
    result = subprocess.run([adb,'devices','-l'],capture_output=True,text=True,check=True,timeout=15)
    return [line.split()[:2] for line in result.stdout.splitlines()[1:] if len(line.split()) >= 2]


def select_device(rows, serial=None):
    ready = [s for s,status in rows if status == 'device' and not s.startswith('emulator-') and ':' not in s]
    if serial:
        if serial not in ready: raise RuntimeError('The selected USB phone is not authorized/online. Unlock it and accept the USB debugging prompt.')
        return serial
    if len(ready) == 1: return ready[0]
    if len(ready) > 1: raise RuntimeError('Several USB phones are available. Use --serial to select exactly one; none was chosen.')
    raise RuntimeError('No authorized USB phone. Connect/unlock it and allow USB debugging, then rerun setup.')


def verify_dependencies(server, backend):
    if hashlib.sha256(Path(server).read_bytes()).hexdigest() != SCRCPY_SHA:
        raise RuntimeError('scrcpy server does not match the pinned official 5.0.1 SHA-256; existing file preserved.')
    entry = Path(backend)
    package = json.loads((entry.parent.parent/'package.json').read_text())
    if not entry.is_file() or package.get('name') != '@mobilenext/mobile-mcp' or package.get('version') != '1.0.9':
        raise RuntimeError('Use the Mobile MCP 1.0.9 lib/index.js entrypoint.')


def configure(state, args):
    state=Path(state); state.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination=state/'config.json'
    if destination.exists():
        raise RuntimeError('Configuration already exists and was preserved. Run doctor, or use --state with a new private directory.')
    adb=executable('adb',args.adb); node=executable('node',args.node)
    serial=select_device(devices(adb),args.serial)
    deps=state/'deps'; deps.mkdir(exist_ok=True,mode=0o700)
    server=Path(args.scrcpy_server).expanduser().resolve() if args.scrcpy_server else deps/'scrcpy-server-v5.0.1'
    backend=Path(args.mobile_mcp).expanduser().resolve() if args.mobile_mcp else deps/'mobile-mcp/node_modules/@mobilenext/mobile-mcp/lib/index.js'
    if args.install_dependencies:
        if not server.exists():
            with urllib.request.urlopen(SCRCPY_URL,timeout=45) as response: data=response.read(2*1024*1024)
            if hashlib.sha256(data).hexdigest() != SCRCPY_SHA: raise RuntimeError('Download checksum failed; no server installed.')
            server.parent.mkdir(parents=True,exist_ok=True);server.write_bytes(data)
        if not backend.exists():
            npm=executable('npm')
            with (state/'dependency-install.log').open('ab') as log:
                subprocess.run([npm,'install','--prefix',str(deps/'mobile-mcp'),'--save-exact','--ignore-scripts','@mobilenext/mobile-mcp@1.0.9'],
                    stdout=log,stderr=log,check=True,timeout=180)
    if not server.exists() or not backend.exists():
        raise RuntimeError('Pinned dependencies missing. Rerun with --install-dependencies, or supply --scrcpy-server and --mobile-mcp paths.')
    verify_dependencies(server,backend)
    config={'serial':serial,'adb':adb,'scrcpy_server':str(server),'backend_command':[node,str(backend)],
        'operation_lock':str(Path(args.operation_lock).expanduser().resolve() if args.operation_lock else state/'operation.lock'),'port':0}
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: json.dump(config,f,indent=2);f.write('\n')
    assert json.loads(destination.read_text()) == config
    return {'configured':True,'phone_bound':True,'private_config':str(destination),'next':'Run phone-harness install-app (macOS), or phone-harness open. Then click Connect.'}


def doctor(state):
    state=Path(state); checks=[]
    try: config=json.loads((state/'config.json').read_text())
    except (OSError,ValueError): return {'ready':False,'checks':[{'name':'configuration','ok':False,'detail':'Run phone-harness setup --install-dependencies first.'}]}
    def check(name,fn):
        try: fn();checks.append({'name':name,'ok':True})
        except Exception as e: checks.append({'name':name,'ok':False,'detail':str(e)})
    check('adb',lambda:executable('adb',config.get('adb')))
    check('node',lambda:executable('node',config['backend_command'][0]))
    check('pinned_dependencies',lambda:verify_dependencies(config['scrcpy_server'],config['backend_command'][1]))
    check('authorized_usb_phone',lambda:select_device(devices(config['adb']),config['serial']))
    return {'ready':all(c['ok'] for c in checks),'checks':checks,'note':'Read-only host/USB checks. This does not establish phone UI acceptance, quiet audio, or long-term reliability.'}
