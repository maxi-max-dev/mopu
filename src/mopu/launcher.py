"""User-invoked local launcher; does not connect or navigate the phone."""
import json
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


def ensure_console(state):
    state = Path(state)
    def existing():
        try:
            endpoint = json.loads((state/'endpoint.json').read_text())
            request = urllib.request.Request(endpoint['url']+'/api/state', headers={'X-Phone-Token':endpoint['token']})
            with urllib.request.urlopen(request,timeout=1) as response:
                if response.status == 200: return endpoint['url']
        except (OSError, ValueError, KeyError): pass
        return None
    url = existing()
    if not url:
        if not (state/'config.json').exists(): raise RuntimeError('Create the private config.json first; see README.md')
        with (state/'console.log').open('ab') as log:
            process = subprocess.Popen([sys.executable,'-m','mopu.cli','--state',str(state),'serve'],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        for _ in range(50):
            url = existing()
            if url: break
            if process.poll() is not None: break
            time.sleep(.1)
        if not url: raise RuntimeError('Console did not start; inspect the private console.log')
    return url


def open_console(state):
    url = ensure_console(state)
    webbrowser.open(url)
    print(url)
