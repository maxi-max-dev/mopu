"""Read-only status parsers. Current sections only; history never proves activity."""
import re

STREAMS = ('SYSTEM', 'RING', 'MUSIC', 'ALARM', 'NOTIFICATION', 'DTMF', 'SYSTEM_ENFORCED', 'VOICE_CALL', 'BLUETOOTH_SCO')
BASIC_STREAMS = ('SYSTEM', 'RING', 'MUSIC', 'ALARM', 'NOTIFICATION', 'DTMF', 'SYSTEM_ENFORCED')
SETTINGS = {
    'system': ('haptic_feedback_enabled', 'vibrate_when_ringing', 'notification_vibration_intensity',
        'ring_vibration_intensity', 'haptic_feedback_intensity', 'hardware_haptic_feedback_intensity',
        'alarm_vibration_intensity', 'media_vibration_intensity', 'keyboard_vibration_enabled',
        'sound_effects_enabled', 'dtmf_tone'),
    'global': ('charging_sounds_enabled', 'charging_vibration_enabled'),
}


def value(pattern, text, cast=str):
    m = re.search(pattern, text, re.M)
    return cast(m[1]) if m else None


def audio_status(text):
    streams = {}
    for name in STREAMS:
        m = re.search(r'^- STREAM_' + name + r'(?::| \(aliased[^\n]*\):)\n(.*?)(?=^\S|\Z)', text, re.M | re.S)
        block = m[1] if m else ''
        muted = value(r'^\s+Muted: (true|false)$', block)
        internal = value(r'^\s+Muted Internally: (true|false)$', block)
        volume = value(r'^\s+streamVolume:\s*(\d+)$', block, int)
        silent = True if muted == 'true' or internal == 'true' or volume == 0 else False if volume is not None else None
        streams[name] = {'silent': silent, 'muted': muted == 'true' if muted else None,
            'volume': volume, 'min': value(r'^\s+Min: (\d+)$', block, int),
            'max': value(r'^\s+Max: (\d+)$', block, int), 'route': value(r'^\s+Devices: (.+)$', block)}
    mode = value(r'^- Actual mode = (MODE_\w+)', text)
    mode = mode or value(r'^- Requested mode = (MODE_\w+)', text)
    call = None if mode is None else mode not in ('MODE_NORMAL', 'MODE_INVALID', 'MODE_CURRENT')
    basic = [streams[n]['silent'] for n in BASIC_STREAMS]
    return {'streams': streams, 'mode': mode, 'call_active': call,
        'basic_silent': all(basic) if all(x is not None for x in basic) else None,
        'ringer': value(r'^- mode \(internal\) = (\w+)', text),
        'communication_route': value(r'^\s*Active communication device: .*?type:([^\s]+)', text),
        'camera_sound_forced': value(r'^\s*mCameraSoundForced=(true|false)', text)}


def camera_status(text):
    m = re.search(r'^Active Camera Clients:\s*\n(.*?)^Allowed user IDs:', text, re.M | re.S)
    if not m: return {'active': None, 'apps': []}
    block = m[1].strip()
    if block == '[]': return {'active': False, 'apps': []}
    if not (block.startswith('[') and block.endswith(']')): return {'active': None, 'apps': []}
    apps = sorted(set(re.findall(r'(?:Client Package Name|Package name|packageName)\s*[:=]\s*([\w.]+)', block, re.I)))
    return {'active': True, 'apps': apps}


def torch_status(text):
    """SystemUI's TorchCallback state, not flash capability or capture history.

    Unavailable can leave the enabled field cached; never report that as off/on.
    This covers the system rear torch only, not camera-controlled flash firing.
    """
    blocks = re.findall(r'^\s*FlashlightController state:[ \t]*\n((?:[ \t]+m\w+=[^\n]*\n?)+)', text, re.M)
    result = {'active': None, 'available': None, 'camera_id': None}
    if len(blocks) != 1: return result
    block = blocks[0]
    camera = value(r'^\s*mCameraId=([^\s]+)\s*$', block)
    enabled = value(r'^\s*mFlashlightEnabled=(true|false)\s*$', block)
    available = value(r'^\s*mTorchAvailable=(true|false)\s*$', block)
    result.update(camera_id=camera if camera and camera != 'null' else None,
                  available=available == 'true' if available else None)
    if result['camera_id'] is not None and result['available'] is True and enabled is not None:
        result['active'] = enabled == 'true'
    return result


def microphone_status(text):
    m = re.search(r'^RecordActivityMonitor dump time:[^\n]*\n(.*?)^Events log: recording', text, re.M | re.S)
    if not m: return {'active': None, 'apps': [], 'silenced': None}
    block = m[1].strip()
    if not block: return {'active': False, 'apps': [], 'silenced': None}
    records = re.findall(r'^riid -?\d+; active\? (true|false)\n(.*?)(?=^riid |\Z)', block + '\n', re.M | re.S)
    if not records: return {'active': None, 'apps': [], 'silenced': None}
    candidates = [b for flag, b in records if flag == 'true']
    # Playback capture/downlink is not proof of microphone use.
    sources = [(value(r'\bsource client=(\w+)', b), b) for b in candidates]
    mic_sources = {'MIC','CAMCORDER','VOICE_RECOGNITION','VOICE_COMMUNICATION','UNPROCESSED','VOICE_PERFORMANCE','VOICE_UPLINK','VOICE_CALL'}
    non_mic_sources = {'REMOTE_SUBMIX','VOICE_DOWNLINK','ECHO_REFERENCE'}
    active = [b for source,b in sources if source in mic_sources]
    unknown = any(source not in mic_sources | non_mic_sources for source,b in sources)
    apps = sorted(set(p for b in active for p in re.findall(r'\bpack(?:age)?(?: name)?[:=]\s*([\w.]+)', b)))
    silenced = [value(r'\bsilenced[:=]\s*(true|false)', b) for b in active]
    return {'active': True if active else None if unknown else False, 'apps': apps,
        'silenced': all(s == 'true' for s in silenced) if silenced and all(s is not None for s in silenced) else None}


def projection_status(text):
    m = re.search(r'^Media Projection:\s*\n(.*)', text, re.M | re.S)
    if not m: return {'active': None, 'apps': []}
    s = m[1].strip()
    if s == 'null': return {'active': False, 'apps': []}
    package = value(r'packageName[=:]\s*([\w.]+)', s) or value(r'^\s*\(([\w.]+), uid=\d+\)', s)
    return {'active': True if package else None, 'apps': [package] if package else []}


def battery_status(text):
    level = value(r'^\s*level: (\d+)', text, int)
    scale = value(r'^\s*scale: (\d+)', text, int)
    temp = value(r'^\s*temperature: (-?\d+)', text, int)
    sources = {name: value(r'^\s*' + name + r' powered: (true|false)', text) for name in ('AC','USB','Wireless','Dock')}
    plugged = True if 'true' in sources.values() else False if any(v == 'false' for v in sources.values()) else None
    status = value(r'^\s*status: (\d+)', text, int)
    limit = value(r'\bmUpperLimit:(\d+)', text, int)
    protected = value(r'\bmChargingDisabled:(true|false)', text)
    return {'percent': round(level * 100 / scale) if level is not None and scale else None,
        'temperature': temp / 10 if temp is not None else None, 'plugged': plugged,
        'sources': [k for k,v in sources.items() if v == 'true'],
        'status': {1:'unknown',2:'charging',3:'discharging',4:'not_charging',5:'full'}.get(status,'unknown'),
        'protection_limit': limit, 'protection_paused': protected == 'true' if protected else None,
        'voltage_mv': value(r'^\s*voltage: (\d+)', text, int)}


def quiet_settings(system, glob):
    result = {}
    for ns, text in (('system',system),('global',glob)):
        for key in SETTINGS[ns]:
            result[key] = value(r'^' + key + r'=(\d+)$', text, int)
    result['zen_mode'] = value(r'^zen_mode=(\d+)$', glob, int)
    return result
