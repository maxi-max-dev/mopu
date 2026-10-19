"""Build a native macOS window around the same local console, without a browser tab."""
import datetime
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def install_app(state, destination):
    if sys.platform != 'darwin':
        raise RuntimeError('The desktop window currently supports macOS; use mopu open on Linux')
    compiler = shutil.which('swiftc')
    if not compiler:
        raise RuntimeError('Install Apple Command Line Tools first (xcode-select --install)')
    app = Path(destination).expanduser().resolve()
    staging = app.with_name(app.stem + '-build-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S')+'.app')
    executable = staging/'Contents/MacOS/Mopu'
    resources = staging/'Contents/Resources'
    executable.parent.mkdir(parents=True); resources.mkdir(parents=True)
    subprocess.run([compiler,'-O',str(Path(__file__).with_name('Desktop.swift')),'-o',str(executable),'-framework','Cocoa','-framework','WebKit'],check=True,timeout=120)
    info = {'CFBundleName':'Mopu','CFBundleDisplayName':'Mopu','CFBundleIdentifier':'local.phone-harness.console',
        'CFBundleExecutable':'Mopu','CFBundlePackageType':'APPL','CFBundleVersion':'0.14.0','CFBundleShortVersionString':'0.14.0',
        'NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}
    (staging/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    (resources/'launch.json').write_text(json.dumps({'python':sys.executable,'state':str(Path(state).resolve())}))
    if app.exists():
        backup = app.with_name(app.stem+'-backup-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S')+'.app')
        app.rename(backup)
    staging.rename(app)
    print(app)
