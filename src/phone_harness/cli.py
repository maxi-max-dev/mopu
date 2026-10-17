import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
from .app import serve
from .mcp import stdio


def main():
    parser = argparse.ArgumentParser(description='Local Android control console and agent-neutral MCP bridge')
    parser.add_argument('--state', type=Path, default=Path.home()/'.local/share/phone-harness')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('serve', help='Run the local console; prints its loopback URL')
    sub.add_parser('status', help='Read the local console state')
    sub.add_parser('open', help='Start the local server if needed and open the console in your browser')
    sub.add_parser('url', help='Start the local server if needed and print its URL without opening a browser')
    desktop = sub.add_parser('install-app', help='Build an independent macOS app window')
    desktop.add_argument('--destination',type=Path,default=Path.home()/'Applications/Phone Harness.app')
    setup = sub.add_parser('setup',help='Bind one authorized USB phone and create a private configuration')
    for flag in ('adb','node','serial','scrcpy-server','mobile-mcp','operation-lock'):
        setup.add_argument('--'+flag)
    setup.add_argument('--install-dependencies',action='store_true',help='Download pinned scrcpy server and install pinned Mobile MCP privately')
    sub.add_parser('doctor',help='Check dependencies and USB authorization without operating the phone')
    mcp = sub.add_parser('mcp', help='Expose phone tools to the agent that launched this process')
    mcp.add_argument('--agent', required=True, help='Stable unique client identity, e.g. codex-work')
    mcp.add_argument('--name', help='Display name, e.g. Codex')
    args = parser.parse_args()
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.command in ('setup','doctor'):
        from .setup import configure, doctor
        try:
            result = configure(args.state,args) if args.command == 'setup' else doctor(args.state)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if result.get('ready') is False: raise SystemExit(1)
        except (RuntimeError,OSError,ValueError) as exc: parser.error(str(exc))
        return
    if args.command == 'install-app':
        from .desktop import install_app
        install_app(args.state,args.destination)
        return
    if args.command == 'url':
        from .launcher import ensure_console
        print(ensure_console(args.state))
        return
    if args.command == 'open':
        from .launcher import open_console
        open_console(args.state)
        return
    if args.command == 'mcp':
        asyncio.run(stdio(args.state, args.agent, args.name or args.agent))
        return
    if args.command == 'status':
        import urllib.request
        endpoint = json.loads((args.state/'endpoint.json').read_text())
        req = urllib.request.Request(endpoint['url']+'/api/state', headers={'X-Phone-Token':endpoint['token']})
        with urllib.request.urlopen(req, timeout=5) as response: print(response.read().decode())
        return
    config_path = args.state/'config.json'
    if not config_path.exists():
        parser.error(f'Create {config_path} using config.example.json first')
    config = json.loads(config_path.read_text())
    for key in ('serial','adb','scrcpy_server','backend_command'):
        if not config.get(key): parser.error(f'Missing config: {key}')
    for key in ('adb','scrcpy_server'):
        if not Path(config[key]).is_file(): parser.error(f'File not found: {key}')
    with (args.state/'server.lock').open('a+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: parser.error('The console is already running; use its endpoint.json URL')
        try: asyncio.run(serve(config, args.state))
        except KeyboardInterrupt: pass


if __name__ == '__main__': main()
