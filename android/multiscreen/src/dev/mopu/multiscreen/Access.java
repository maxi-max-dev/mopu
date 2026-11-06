package dev.mopu.multiscreen;
import android.accessibilityservice.AccessibilityService;
import android.view.accessibility.AccessibilityEvent;
public class Access extends AccessibilityService {
 public static volatile Access live;
 protected void onServiceConnected(){live=this;}
 public void onAccessibilityEvent(AccessibilityEvent e){}
 public void onInterrupt(){}
 public void onDestroy(){live=null;super.onDestroy();}
}
