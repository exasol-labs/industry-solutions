import SwiftUI
import WebKit
#if canImport(AppKit)
import AppKit
#endif

// MARK: - SwiftUI wrapper

struct MarkdownView {
    let markdown: String
    @Environment(\.colorScheme) private var colorScheme

    // MARK: - PDF export

    @MainActor
    static func generatePDF(markdown: String, isDark: Bool = false) async -> Data? {
        let html = pagePDF(markdown: markdown)
        return await withCheckedContinuation { cont in
            let loader = _PDFLoader()
            loader.continuation = cont
            // Layout viewport = A4 printable width (595 – 54 – 54 = 487 pt)
            let wv = WKWebView(frame: CGRect(x: 0, y: 0, width: 487, height: 842))
            loader.webView = wv
            wv.navigationDelegate = loader
            wv.loadHTMLString(html, baseURL: nil)
        }
    }

    // MARK: - Print-optimised HTML page (A4, always light)

    static func pagePDF(markdown: String) -> String {
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
        + cssPDF()
        + "</style></head><body>"
        + mdToHTML(markdown)
        + "</body></html>"
    }

    private static func cssPDF() -> String {
        let fg     = "#1C1C1E"
        let sec    = "#6C6C70"
        let code   = "#F2F2F7"
        let brd    = "#D1D1D6"
        let altRow = "#F9F9FB"
        // printable height per page: A4(842) – marginTop(54) – marginBottom(72) = 716 pt
        return """
        *{box-sizing:border-box}
        body{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;font-size:11pt;
             line-height:1.6;color:\(fg);background:#fff;margin:0;padding:0;word-break:break-word}
        h1{font-size:20pt;font-weight:700;margin:16pt 0 8pt;padding-bottom:4pt;border-bottom:1.5pt solid \(brd)}
        h2{font-size:16pt;font-weight:600;margin:14pt 0 6pt}
        h3{font-size:13pt;font-weight:600;margin:10pt 0 4pt;color:\(sec)}
        p{margin:5pt 0}
        ul,ol{padding-left:18pt;margin:5pt 0}
        li{margin:2pt 0}
        code{font-family:'SF Mono','Courier New',monospace;font-size:9pt;
             background:\(code);padding:1pt 4pt;border-radius:3pt}
        pre{background:\(code);padding:10pt;border-radius:6pt;margin:8pt 0}
        pre code{background:none;padding:0}
        table{border-collapse:collapse;width:100%;margin:10pt 0;font-size:10pt}
        th{background:\(code);font-weight:600;padding:6pt 10pt;text-align:left;border:0.5pt solid \(brd)}
        td{padding:5pt 10pt;border:0.5pt solid \(brd)}
        tr:nth-child(even) td{background:\(altRow)}
        thead{display:table-header-group}
        tr{break-inside:avoid;page-break-inside:avoid}
        hr{border:none;border-top:0.75pt solid \(brd);margin:14pt 0}
        strong{font-weight:600}
        em{font-style:italic}
        blockquote{margin:8pt 0;padding:6pt 14pt;border-left:3pt solid \(brd);color:\(sec)}
        .page-break{page-break-before:always;break-before:page;margin:0;height:0}
        .title-page{height:716pt;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
        .title-page h1{font-size:26pt;border-bottom:none;padding-bottom:0;margin:0 0 8pt}
        .tp-app{font-size:10pt;letter-spacing:.08em;text-transform:uppercase;color:\(sec);margin:0 0 18pt}
        .tp-sub{font-size:12pt;color:\(sec);margin:0 0 26pt;font-style:italic}
        .tp-rule{border:none;border-top:0.5pt solid \(brd);width:50%;margin:0 auto 14pt}
        .tp-meta{font-size:10pt;color:\(sec);margin:3pt 0}
        .toc ol{list-style:none;padding:0;margin:8pt 0}
        .toc li{display:flex;justify-content:space-between;align-items:baseline;padding:3pt 0;border-bottom:0.5pt solid \(brd)}
        .toc a{color:inherit;text-decoration:none;flex:1}
        .toc-pg{color:\(sec);font-size:10pt;min-width:20pt;text-align:right}
        """
    }

    // MARK: - HTML page

    static func page(markdown: String, isDark: Bool) -> String {
        "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><style>"
        + css(isDark: isDark)
        + "</style></head><body>"
        + mdToHTML(markdown)
        + "</body></html>"
    }

    private static func css(isDark: Bool) -> String {
        let fg     = isDark ? "#F2F2F7" : "#1C1C1E"
        let sec    = isDark ? "#8E8E93" : "#6C6C70"
        let code   = isDark ? "#2C2C2E" : "#F2F2F7"
        let brd    = isDark ? "#38383A" : "#D1D1D6"
        let altRow = isDark ? "#242426" : "#F9F9FB"
        return """
        *{box-sizing:border-box}
        body{font-family:-apple-system,'Helvetica Neue';font-size:16px;line-height:1.65;
             color:\(fg);background:transparent;margin:0;padding:20px 24px 48px;word-break:break-word}
        h1{font-size:26px;font-weight:700;margin:20px 0 10px;padding-bottom:6px;border-bottom:2px solid \(brd)}
        h2{font-size:21px;font-weight:600;margin:16px 0 8px}
        h3{font-size:17px;font-weight:600;margin:12px 0 6px;color:\(sec)}
        p{margin:8px 0}
        ul,ol{padding-left:22px;margin:8px 0}
        li{margin:4px 0}
        code{font-family:'SF Mono','Courier New',monospace;font-size:14px;
             background:\(code);padding:2px 6px;border-radius:5px}
        pre{background:\(code);padding:14px;border-radius:10px;margin:10px 0;overflow-x:auto}
        pre code{background:none;padding:0;font-size:13px}
        table{border-collapse:collapse;width:100%;margin:14px 0;font-size:15px}
        th{background:\(code);font-weight:600;padding:9px 13px;text-align:left;border:1px solid \(brd)}
        td{padding:7px 13px;border:1px solid \(brd)}
        tr:nth-child(even) td{background:\(altRow)}
        hr{border:none;border-top:1px solid \(brd);margin:18px 0}
        strong{font-weight:600}
        em{font-style:italic}
        .page-break{page-break-before:always;break-before:page;margin:0;height:0}
        .title-page{padding:60px 24px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;border-bottom:1px solid \(brd);margin-bottom:24px}
        .title-page h1{font-size:28px;border-bottom:none;padding-bottom:0;margin:0 0 8px}
        .tp-app{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:\(sec);margin:0 0 20px}
        .tp-sub{font-size:14px;color:\(sec);margin:0 0 28px;font-style:italic}
        .tp-rule{border:none;border-top:1px solid \(brd);width:50%;margin:0 auto 16px}
        .tp-meta{font-size:13px;color:\(sec);margin:3px 0}
        .toc ol{list-style:none;padding:0;margin:8px 0}
        .toc li{display:flex;justify-content:space-between;align-items:baseline;padding:4px 0;border-bottom:1px solid \(brd)}
        .toc a{color:inherit;text-decoration:none;flex:1}
        .toc-pg{color:\(sec);font-size:13px;min-width:20px;text-align:right}
        """
    }

    // MARK: - Markdown → HTML

    private static func mdToHTML(_ md: String) -> String {
        let lines = md.components(separatedBy: "\n")
        var html  = ""
        var i     = 0
        var inUL  = false, inOL = false, inCode = false
        var codeLines: [String] = []
        var tableLines: [String] = []

        func closeUL()    { if inUL { html += "</ul>"; inUL = false } }
        func closeOL()    { if inOL { html += "</ol>"; inOL = false } }
        func flushTable() {
            guard !tableLines.isEmpty else { return }
            html += renderTable(tableLines); tableLines = []
        }
        func closeLists() { closeUL(); closeOL() }

        while i < lines.count {
            let raw     = lines[i]
            let trimmed = raw.trimmingCharacters(in: .whitespaces)

            // Code fence
            if trimmed.hasPrefix("```") {
                if inCode {
                    html += "<pre><code>" + codeLines.joined(separator: "\n").esc() + "</code></pre>"
                    codeLines = []; inCode = false
                } else {
                    closeLists(); flushTable(); inCode = true
                }
                i += 1; continue
            }
            if inCode { codeLines.append(raw); i += 1; continue }

            // Raw HTML div block passthrough
            if trimmed.lowercased().hasPrefix("<div") {
                closeLists(); flushTable()
                var block = trimmed
                let lo    = trimmed.lowercased()
                var depth = lo.components(separatedBy: "<div").count - 1
                          - (lo.components(separatedBy: "</div>").count - 1)
                while depth > 0 && i + 1 < lines.count {
                    i += 1
                    let line = lines[i]
                    block += "\n" + line
                    let ll = line.lowercased()
                    depth += ll.components(separatedBy: "<div").count - 1
                    depth -= ll.components(separatedBy: "</div>").count - 1
                }
                html += block
                i += 1; continue
            }

            // Raw HTML block passthrough (e.g. programmatically generated tables with explicit styling)
            if trimmed.lowercased().hasPrefix("<table") {
                closeLists(); flushTable()
                var block = trimmed
                while !block.lowercased().contains("</table>") && i + 1 < lines.count {
                    i += 1
                    block += "\n" + lines[i]
                }
                html += block
                i += 1; continue
            }

            // Table
            if trimmed.hasPrefix("|") {
                closeLists()
                tableLines.append(trimmed)
                i += 1; continue
            } else { flushTable() }

            let isBullet  = trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ")
            let isOrdered = trimmed.range(of: #"^\d+\. "#, options: .regularExpression) != nil
            if !isBullet  { closeUL() }
            if !isOrdered { closeOL() }

            if trimmed.isEmpty {
                html += "<br>"
            } else if trimmed.hasPrefix("### ") {
                html += "<h3>" + inl(String(trimmed.dropFirst(4))) + "</h3>"
            } else if trimmed.hasPrefix("## ") {
                html += "<h2>" + inl(String(trimmed.dropFirst(3))) + "</h2>"
            } else if trimmed.hasPrefix("# ") {
                html += "<h1>" + inl(String(trimmed.dropFirst(2))) + "</h1>"
            } else if trimmed == "---" || trimmed == "***" || trimmed == "___" {
                html += "<hr>"
            } else if isBullet {
                if !inUL { html += "<ul>"; inUL = true }
                html += "<li>" + inl(String(trimmed.dropFirst(2))) + "</li>"
            } else if isOrdered {
                if !inOL { html += "<ol>"; inOL = true }
                let body = trimmed.replacingOccurrences(
                    of: #"^\d+\. "#, with: "", options: .regularExpression)
                html += "<li>" + inl(body) + "</li>"
            } else {
                html += "<p>" + inl(trimmed) + "</p>"
            }
            i += 1
        }

        closeLists(); flushTable()
        if inCode {
            html += "<pre><code>" + codeLines.joined(separator: "\n").esc() + "</code></pre>"
        }
        return html
    }

    // MARK: - Table renderer

    private static func renderTable(_ rows: [String]) -> String {
        // Drop separator rows (contain only |, -, :, space)
        let dataRows = rows.filter { row in
            !row.replacingOccurrences(of: "[|:\\- ]", with: "", options: .regularExpression).isEmpty
        }
        guard !dataRows.isEmpty else { return "" }

        func cells(_ r: String) -> [String] {
            var parts = r.components(separatedBy: "|")
            if parts.first?.trimmingCharacters(in: .whitespaces).isEmpty == true { parts.removeFirst() }
            if parts.last?.trimmingCharacters(in: .whitespaces).isEmpty  == true { parts.removeLast()  }
            return parts.map { $0.trimmingCharacters(in: .whitespaces) }
        }

        var h = "<table>"
        for (idx, row) in dataRows.enumerated() {
            let cs = cells(row)
            if idx == 0 {
                h += "<tr>" + cs.map { "<th>" + inl($0) + "</th>" }.joined() + "</tr>"
            } else {
                h += "<tr>" + cs.map { "<td>" + inl($0) + "</td>" }.joined() + "</tr>"
            }
        }
        return h + "</table>"
    }

    // MARK: - Inline markdown (bold, italic, code)

    private static func inl(_ text: String) -> String {
        var s = text.esc()
        s = s.replacingOccurrences(of: "&lt;br&gt;", with: "<br>")
        s = s.replacingOccurrences(of: #"\*\*\*(.+?)\*\*\*"#,
                                   with: "<strong><em>$1</em></strong>", options: .regularExpression)
        s = s.replacingOccurrences(of: #"\*\*(.+?)\*\*"#,
                                   with: "<strong>$1</strong>",          options: .regularExpression)
        s = s.replacingOccurrences(of: #"\*([^*\n]+)\*"#,
                                   with: "<em>$1</em>",                  options: .regularExpression)
        s = s.replacingOccurrences(of: #"`([^`]+)`"#,
                                   with: "<code>$1</code>",              options: .regularExpression)
        return s
    }
}

// MARK: - SwiftUI representable conformance (UIKit on iOS, AppKit on macOS)

#if os(iOS)
extension MarkdownView: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView {
        let wv = WKWebView()
        wv.isOpaque = false
        wv.backgroundColor = .clear
        wv.scrollView.backgroundColor = .clear
        return wv
    }

    func updateUIView(_ wv: WKWebView, context: Context) {
        wv.loadHTMLString(MarkdownView.page(markdown: markdown, isDark: colorScheme == .dark), baseURL: nil)
    }
}
#else
extension MarkdownView: NSViewRepresentable {
    func makeNSView(context: Context) -> WKWebView {
        let wv = WKWebView()
        wv.setValue(false, forKey: "drawsBackground")
        return wv
    }

    func updateNSView(_ wv: WKWebView, context: Context) {
        wv.loadHTMLString(MarkdownView.page(markdown: markdown, isDark: colorScheme == .dark), baseURL: nil)
    }
}
#endif

// MARK: - WKWebView PDF helper (self-retains until PDF is ready, since WKWebView holds delegate weakly)

final class _PDFLoader: NSObject, WKNavigationDelegate {
    var continuation: CheckedContinuation<Data?, Never>?
    var webView: WKWebView?
    private var selfRef: _PDFLoader?

    // A4 page geometry (points)
    private let paperW:  CGFloat = 595
    private let paperH:  CGFloat = 842
    private let mTop:    CGFloat = 54
    private let mSide:   CGFloat = 54
    private let mBottom: CGFloat = 72

    private var paperRect: CGRect { CGRect(x: 0, y: 0, width: paperW, height: paperH) }
    private var printRect: CGRect { CGRect(x: mSide, y: mTop,
                                           width:  paperW - 2 * mSide,
                                           height: paperH - mTop - mBottom) }

    override init() { super.init(); selfRef = self }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Inject page numbers into TOC spans.
        // Each .page-break div (height:0) causes a page boundary in print layout but not in
        // the browser's visual flow, so we must account for the "waste" each break adds.
        let ph = printRect.height
        let js = """
        (function(){
            var ph = \(ph);
            var pbYs = Array.from(document.querySelectorAll('.page-break'))
                .map(function(el){ return el.getBoundingClientRect().top + window.scrollY; })
                .sort(function(a,b){ return a - b; });
            for (var n = 1; n <= 30; n++) {
                var ch = document.getElementById('ch' + n);
                if (!ch) break;
                var visY = ch.getBoundingClientRect().top + window.scrollY;
                var extra = 0;
                for (var j = 0; j < pbYs.length; j++) {
                    if (pbYs[j] > visY) break;
                    var rem = (pbYs[j] + extra) % ph;
                    if (rem > 0) extra += ph - rem;
                }
                var pg = Math.floor((visY + extra) / ph) + 1;
                var sp = document.getElementById('toc-pg-' + n);
                if (sp) sp.textContent = pg;
            }
        })()
        """
        webView.evaluateJavaScript(js) { [weak self] _, _ in
            guard let self else { return }
            DispatchQueue.main.async { self.renderPDF(webView: webView) }
        }
    }

#if os(iOS)
    private func renderPDF(webView: WKWebView) {
        let renderer = UIPrintPageRenderer()
        renderer.addPrintFormatter(webView.viewPrintFormatter(), startingAtPageAt: 0)
        renderer.setValue(NSValue(cgRect: paperRect), forKey: "paperRect")
        renderer.setValue(NSValue(cgRect: printRect),  forKey: "printableRect")

        let pageCount = renderer.numberOfPages
        guard pageCount > 0 else { finish(with: nil); return }
        renderer.prepare(forDrawingPages: NSMakeRange(0, pageCount))

        let numAttrs: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 9),
            .foregroundColor: UIColor(white: 0.43, alpha: 1)
        ]

        let data = NSMutableData()
        UIGraphicsBeginPDFContextToData(data, paperRect, nil)
        for i in 0..<pageCount {
            UIGraphicsBeginPDFPage()
            renderer.drawPage(at: i, in: printRect)

            // Page number centred in the bottom margin
            let label = "\(i + 1)" as NSString
            let sz    = label.size(withAttributes: numAttrs)
            label.draw(at: CGPoint(x: (paperW - sz.width) / 2,
                                   y: paperH - mBottom / 2 - sz.height / 2),
                       withAttributes: numAttrs)
        }
        UIGraphicsEndPDFContext()
        finish(with: data as Data)
    }
#else
    @MainActor
    private func renderPDF(webView: WKWebView) {
        // Render via WebKit's own PDF generator. Driving an NSPrintOperation from a
        // WKWebView crashes inside AppKit's pagination validation (`_validatePagination`)
        // on macOS, and the App Sandbox blocks the print panel, so we avoid the print
        // system entirely.
        webView.createPDF(configuration: WKPDFConfiguration()) { [weak self] result in
            switch result {
            case .success(let data): self?.finish(with: data)
            case .failure:           self?.finish(with: nil)
            }
        }
    }
#endif

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        DispatchQueue.main.async { self.finish(with: nil) }
    }

    private func finish(with data: Data?) {
        continuation?.resume(returning: data)
        continuation = nil
        webView = nil
        selfRef = nil
    }
}

// MARK: - HTML escaping helper

private extension String {
    func esc() -> String {
        self.replacingOccurrences(of: "&",  with: "&amp;")
            .replacingOccurrences(of: "<",  with: "&lt;")
            .replacingOccurrences(of: ">",  with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }
}
