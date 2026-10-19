"""Describe supported routes without claiming OEM privileges or device success."""
from .device import ALLOWED

READS = {'mobile_list_apps','mobile_get_foreground_app','mobile_get_screen_size',
         'mobile_list_elements_on_screen','mobile_take_screenshot','mobile_get_orientation'}
UI = {'mobile_click_on_screen_at_coordinates','mobile_double_tap_on_screen',
      'mobile_long_press_on_screen_at_coordinates','mobile_swipe_on_screen',
      'mobile_type_keys','mobile_press_button'}
LABELS = {
 'mobile_list_apps':'查看应用列表','mobile_get_foreground_app':'读取前台应用',
 'mobile_launch_app':'启动应用','mobile_open_url':'打开网页链接',
 'mobile_get_screen_size':'读取输入坐标尺寸','mobile_get_orientation':'读取屏幕方向',
 'mobile_list_elements_on_screen':'读取界面文字与位置','mobile_take_screenshot':'观察屏幕',
 'mobile_click_on_screen_at_coordinates':'点击','mobile_double_tap_on_screen':'双击',
 'mobile_long_press_on_screen_at_coordinates':'长按','mobile_swipe_on_screen':'滑动',
 'mobile_type_keys':'输入文字','mobile_press_button':'系统导航',
}


def catalog(connected, owner, available=None, checked_at=None):
    items = []
    for name in sorted(ALLOWED):
        read = name in READS
        availability = 'unconfirmed' if available is None else 'provided' if name in available else 'unavailable'
        items.append({'name':name,'label':LABELS[name], 'route':'ui' if name in UI else 'direct',
            'access':'read' if read else 'change','availability':availability,
            'requires':['exclusive_lease'] + ([] if read else ['fresh_observation','task_authorization']),
            'result_semantics':'返回当前读数；空白或错误不可当作已观察' if read else '调用返回不证明目标完成，之后必须重新读回',
            'verification':'新鲜界面/前台应用读回；由原助手判断任务条件',
            'checked_at':checked_at, 'ready_for_lease':bool(connected and owner=='agent' and availability=='provided')})
    return {'version':1,'items':items,
            'notice':'代码支持不等于设备已提供；设备已提供不等于任务已成功。实际参数以 phone_tools 为准。',
            'limits':['不提供厂商系统级权限','没有文件传输、支付或通知发送接口','不启动或替换原助手'],
            'health':'电池、静音、设备使用状态可通过 phone_status 读取；每项含核验时间与 freshness。'}
