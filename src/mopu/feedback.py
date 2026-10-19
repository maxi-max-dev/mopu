"""Ephemeral input descriptions. Never include typed text, URLs or screen content."""
import math
import re

KEYS = {3:'主页',4:'返回',19:'向上',20:'向下',21:'向左',22:'向右',61:'切换焦点',
        66:'确认键',67:'删除键',111:'退出',122:'移到开头',123:'移到末尾',187:'最近应用',
        'HOME':'主页','BACK':'返回','ENTER':'确认键','DPAD_CENTER':'确认键',
        'DPAD_UP':'向上','DPAD_DOWN':'向下','DPAD_LEFT':'向左','DPAD_RIGHT':'向右'}
COORDINATE_TOOLS = {'mobile_click_on_screen_at_coordinates','mobile_double_tap_on_screen',
                    'mobile_long_press_on_screen_at_coordinates','mobile_swipe_on_screen'}


def screen_size(raw):
    sizes = re.findall(r'^(?:Physical|Override) size: (\d+)x(\d+)\s*$', raw, re.M)
    return tuple(map(int, sizes[-1])) if sizes else None


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError): return None


def describe(name, args, natural=None, video=(0,0)):
    """Paths mirror the pinned Android Mobile MCP 1.0.9 input implementation.

    wm size is natural orientation. Touch coordinates follow the current display.
    Unreadable size/aspect mismatch yields a label only, never a guessed point.
    """
    kinds = {'mobile_click_on_screen_at_coordinates':('tap','点击'),
             'mobile_double_tap_on_screen':('double','双击'),
             'mobile_long_press_on_screen_at_coordinates':('hold','长按'),
             'mobile_swipe_on_screen':('swipe','滑动'),
             'mobile_type_keys':('text','输入文字'),
             'mobile_launch_app':('app','打开应用'),
             'mobile_open_url':('app','打开链接'),
             'mobile_press_button':('key',KEYS.get(args.get('button'),'导航按键'))}
    if name not in kinds: return None
    kind,label = kinds[name]
    cue = {'kind':kind,'label':label,'points':[],'video':list(video)}
    if name not in COORDINATE_TOOLS or not natural or not all(natural) or not all(video): return cue
    nw,nh = natural
    w,h = (max(natural),min(natural)) if video[0]>video[1] else (min(natural),max(natural))
    if abs((w/h)/(video[0]/video[1])-1) > .025: return cue
    x,y = number(args.get('x')),number(args.get('y'))
    if kind=='swipe':
        direction = args.get('direction')
        cue['label'] = {'up':'向上滑动','down':'向下滑动','left':'向左滑动','right':'向右滑动'}.get(direction,'滑动')
        if direction not in ('up','down','left','right'): return cue
        # A center-based backend swipe ignores distance, starting at 20/80%.
        if x is None or y is None:
            points = {'up':[(nw//2,math.floor(nh*.8)),(nw//2,math.floor(nh*.2))],
                      'down':[(nw//2,math.floor(nh*.2)),(nw//2,math.floor(nh*.8))],
                      'left':[(math.floor(nw*.8),math.floor(nh*.5)),(math.floor(nw*.2),math.floor(nh*.5))],
                      'right':[(math.floor(nw*.2),math.floor(nh*.5)),(math.floor(nw*.8),math.floor(nh*.5))]}[direction]
        else:
            distance = number(args.get('distance')) or math.floor((nh if direction in ('up','down') else nw)*.3)
            end = {'up':(x,max(0,y-distance)), 'down':(x,min(nh,y+distance)),
                   'left':(max(0,x-distance),y), 'right':(min(nw,x+distance),y)}[direction]
            points = [(x,y),end]
    else: points = [(x,y)]
    if any(x is None or y is None or not 0<=x<=w or not 0<=y<=h for x,y in points): return cue
    cue['points'] = [[round(x/w,6),round(y/h,6)] for x,y in points]
    return cue
