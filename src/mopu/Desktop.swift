import Cocoa
import WebKit

final class PhoneApp: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var origin: URL?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "关于 Mopu", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出 Mopu", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let edit = NSMenu(title:"编辑"); editItem.submenu = edit
        for (title, selector, key) in [("剪切","cut:","x"),("复制","copy:","c"),("粘贴","paste:","v"),("全选","selectAll:","a")] {
            edit.addItem(withTitle:title,action:Selector(selector),keyEquivalent:key)
        }
        let viewItem = NSMenuItem(); menu.addItem(viewItem)
        let view = NSMenu(title:"视图"); viewItem.submenu = view
        let reload = view.addItem(withTitle:"重新加载控制台",action:#selector(reloadConsole(_:)),keyEquivalent:"r")
        reload.target = self
        NSApp.mainMenu = menu
        window = NSWindow(contentRect:NSRect(x:0,y:0,width:1280,height:850),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title = "Mopu"
        window.minSize = NSSize(width:850,height:640)
        window.setFrameAutosaveName("PhoneHarnessWindow")
        window.appearance = NSAppearance(named:.aqua)
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        web = WKWebView(frame:window.contentView!.bounds,configuration:config)
        web.autoresizingMask = [.width,.height]; web.navigationDelegate = self
        window.contentView = web
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
        web.loadHTMLString("<body style='background:#f8f9f7;color:#72776f;font:18px -apple-system;padding:60px'>正在启动 Mopu…</body>",baseURL:nil)
        DispatchQueue.global(qos:.userInitiated).async { self.startConsole() }
    }
    @objc func reloadConsole(_ sender:Any?) {
        DispatchQueue.global(qos:.userInitiated).async { self.startConsole() }
    }
    func startConsole() {
        do {
            let file = Bundle.main.url(forResource:"launch",withExtension:"json")!
            let settings = try JSONSerialization.jsonObject(with:Data(contentsOf:file)) as! [String:String]
            let proc = Process(); proc.executableURL = URL(fileURLWithPath:settings["python"]!)
            proc.arguments = ["-m","mopu.cli","--state",settings["state"]!,"url"]
            let pipe = Pipe(); proc.standardOutput = pipe; proc.standardError = pipe
            try proc.run(); let data=pipe.fileHandleForReading.readDataToEndOfFile(); proc.waitUntilExit()
            let result=String(data:data,encoding:.utf8)?.trimmingCharacters(in:.whitespacesAndNewlines) ?? ""
            guard proc.terminationStatus == 0, let url=URL(string:result), url.scheme == "http", url.host == "127.0.0.1" else {
                throw NSError(domain:"PhoneHarness",code:1,userInfo:[NSLocalizedDescriptionKey:result])
            }
            DispatchQueue.main.async { self.origin=url; self.web.load(URLRequest(url:url)) }
        } catch { DispatchQueue.main.async {
            let alert=NSAlert(); alert.messageText="控制台未能启动";alert.informativeText=error.localizedDescription;alert.runModal()
        }}
    }
    func webView(_ webView:WKWebView, decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping (WKNavigationActionPolicy)->Void) {
        guard let url=action.request.url else { decisionHandler(.cancel); return }
        let local = url.scheme == "http" && url.host == origin?.host && url.port == origin?.port
        decisionHandler(local || (origin == nil && url.scheme == "about") ? .allow : .cancel)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
}
let app = NSApplication.shared
let delegate = PhoneApp(); app.delegate=delegate; app.run()
