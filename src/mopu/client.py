"""Portable shell client using the same broker. No daemon, replay or device access."""
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import aiohttp
from .mcp import Client, TOOLS
from .tasks import atomic


async def call_tool(state, agent, name, tool, arguments):
    if tool == 'list': return {'tools':TOOLS}
    if tool not in {t['name'] for t in TOOLS}: raise ValueError('Unknown tool; use list')
    if not isinstance(arguments, dict): raise ValueError('Arguments must be an object')
    if not agent or len(agent)>100: raise ValueError('Use a unique agent identity, 1–100 characters')
    directory = Path(state)/'clients'
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    path = directory/(hashlib.sha256(agent.encode()).hexdigest()+'.json')
    fd = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        # Fail promptly on simultaneous calls: do not queue an uncertain input.
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('This client has an in-flight call; inspect its result before issuing another')
        client = Client(state, agent, name)
        if path.exists():
            saved = json.loads(path.read_text())
            client.endpoint, client.identity, client.lease = saved['endpoint'], saved['identity'], saved.get('lease')
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=65)) as session:
            client.session = session
            try:
                return await client.request(tool.removeprefix('phone_'), arguments)
            finally:
                # Private tokens never appear in output. Never replay a failed call.
                atomic(path, {'endpoint':client.endpoint,'identity':client.identity,'lease':client.lease})
    finally:
        os.close(fd)
