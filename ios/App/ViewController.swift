import UIKit
import WebKit
import ExternalAccessory

/// Thin shell around the logger page (index.html). The page talks to the dongle through a small
/// `AndroidBT` object (same name as on Android, so the page has one code path); this class moves bytes
/// between that object and the MFi accessory (OBDLink MX+) using ExternalAccessory.
/// All OBD logic, including "only send read requests", lives in the page.
final class ViewController: UIViewController, WKScriptMessageHandler, WKNavigationDelegate, StreamDelegate {
    private var web: WKWebView!
    private var session: EASession?
    private var pending = Data()
    private var selfClose = false
    private var connectedID = 0

    private let shim = """
    window.__btList = '[]';
    window.AndroidBT = {
      hasPerm: function(){ return true; },
      askPerm: function(){},
      refresh: function(){ window.webkit.messageHandlers.bt.postMessage({op:'list'}); },
      listPaired: function(){ return window.__btList; },
      connect: function(a){ window.webkit.messageHandlers.bt.postMessage({op:'connect', addr:String(a)}); },
      write: function(s){ window.webkit.messageHandlers.bt.postMessage({op:'write', data:s}); },
      close: function(){ window.webkit.messageHandlers.bt.postMessage({op:'close'}); },
      save: function(n,t,m){ window.webkit.messageHandlers.bt.postMessage({op:'save', name:n, text:t}); return 'the share sheet (choose Save to Files)'; }
    };
    """

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "bt")
        cfg.userContentController.addUserScript(WKUserScript(source: shim, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(web)
        NSLayoutConstraint.activate([
            web.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            web.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            web.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
        if let url = Bundle.main.url(forResource: "index", withExtension: "html"),
           let html = try? String(contentsOf: url, encoding: .utf8) {
            web.loadHTMLString(html, baseURL: URL(string: "https://fastobd.app/"))
        }
        EAAccessoryManager.shared().registerForLocalNotifications()
        NotificationCenter.default.addObserver(self, selector: #selector(accessoryChanged), name: .EAAccessoryDidConnect, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(accessoryGone(_:)), name: .EAAccessoryDidDisconnect, object: nil)
    }

    // MARK: JS plumbing
    private func js(_ code: String) {
        DispatchQueue.main.async { self.web.evaluateJavaScript(code, completionHandler: nil) }
    }
    private func lit(_ s: String) -> String {
        guard let d = try? JSONSerialization.data(withJSONObject: [s]),
              let j = String(data: d, encoding: .utf8) else { return "\"\"" }
        return String(j.dropFirst().dropLast())
    }
    private func pageLog(_ s: String) { js("try{log(\(lit(s)))}catch(e){}") }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { pushList() }

    // MARK: accessories
    private func pushList() {
        var arr: [[String: String]] = []
        for a in EAAccessoryManager.shared().connectedAccessories {
            arr.append(["name": a.name.isEmpty ? a.modelNumber : a.name, "addr": String(a.connectionID)])
        }
        if let d = try? JSONSerialization.data(withJSONObject: arr), let s = String(data: d, encoding: .utf8) {
            js("window.__btList = \(lit(s));")
        }
    }
    @objc private func accessoryChanged() { pushList() }
    @objc private func accessoryGone(_ n: Notification) {
        pushList()
        if let a = n.userInfo?[EAAccessoryKey] as? EAAccessory, a.connectionID == connectedID, !selfClose {
            closeSession()
            js("window.__btClosed()")
        }
    }

    private var supportedProtocols: Set<String> {
        let arr = Bundle.main.object(forInfoDictionaryKey: "UISupportedExternalAccessoryProtocols") as? [String] ?? []
        return Set(arr)
    }

    // MARK: messages from the page
    func userContentController(_ uc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let m = message.body as? [String: Any], let op = m["op"] as? String else { return }
        switch op {
        case "list":
            pushList()
            if EAAccessoryManager.shared().connectedAccessories.isEmpty {
                // nothing connected yet: let iOS show its own accessory picker for MFi Bluetooth devices
                EAAccessoryManager.shared().showBluetoothAccessoryPicker(withNameFilter: nil) { [weak self] _ in self?.pushList() }
            }
        case "connect":
            connect(addr: m["addr"] as? String ?? "")
        case "write":
            if let s = m["data"] as? String, let d = s.data(using: .isoLatin1) { pending.append(d); flush() }
        case "close":
            selfClose = true
            closeSession()
        case "save":
            save(name: m["name"] as? String ?? "obd.csv", text: m["text"] as? String ?? "")
        default: break
        }
    }

    private func connect(addr: String) {
        closeSession()
        selfClose = false
        guard let acc = EAAccessoryManager.shared().connectedAccessories.first(where: { String($0.connectionID) == addr }) else {
            js("window.__btConnected(false, 'accessory not connected. Pair it in iPhone Settings > Bluetooth first')")
            return
        }
        pageLog("Accessory protocols: " + acc.protocolStrings.joined(separator: ", "))
        let ours = supportedProtocols
        guard let proto = acc.protocolStrings.first(where: { ours.contains($0) }) else {
            js("window.__btConnected(false, \(lit("this app does not know the accessory's protocol (" + acc.protocolStrings.joined(separator: ", ") + ")")))")
            return
        }
        guard let s = EASession(accessory: acc, forProtocol: proto),
              let i = s.inputStream, let o = s.outputStream else {
            js("window.__btConnected(false, 'could not open a session. Close the OBDLink app and try again')")
            return
        }
        session = s
        connectedID = acc.connectionID
        for st in [i, o] {
            st.delegate = self
            st.schedule(in: .main, forMode: .default)
            st.open()
        }
        js("window.__btConnected(true, '')")
    }

    private func closeSession() {
        if let s = session {
            for st in [s.inputStream, s.outputStream] {
                st?.close()
                st?.remove(from: .main, forMode: .default)
                st?.delegate = nil
            }
        }
        session = nil
        pending.removeAll()
    }

    private func flush() {
        guard let o = session?.outputStream else { return }
        while !pending.isEmpty && o.hasSpaceAvailable {
            let n = pending.withUnsafeBytes { o.write($0.bindMemory(to: UInt8.self).baseAddress!, maxLength: pending.count) }
            if n <= 0 { break }
            pending.removeFirst(n)
        }
    }

    func stream(_ aStream: Stream, handle eventCode: Stream.Event) {
        switch eventCode {
        case .hasBytesAvailable:
            guard let i = session?.inputStream else { return }
            var buf = [UInt8](repeating: 0, count: 1024)
            while i.hasBytesAvailable {
                let n = i.read(&buf, maxLength: buf.count)
                if n <= 0 { break }
                let s = String(decoding: buf[0..<n].map { UInt16($0) }, as: UTF16.self)   // bytes as Latin-1
                js("window.__btRx(\(lit(s)))")
            }
        case .hasSpaceAvailable:
            flush()
        case .endEncountered, .errorOccurred:
            if !selfClose && session != nil {
                closeSession()
                js("window.__btClosed()")
            }
        default: break
        }
    }

    // MARK: saving
    private func save(name: String, text: String) {
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let url = dir.appendingPathComponent(name)
        do { try text.write(to: url, atomically: true, encoding: .utf8) } catch { pageLog("Save failed: \(error.localizedDescription)"); return }
        DispatchQueue.main.async {
            let vc = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            vc.popoverPresentationController?.sourceView = self.view
            self.present(vc, animated: true)
        }
    }
}
