//  PlatformCompat.swift
//
//  Cross-platform shims that let the iPad-first SwiftUI views compile for
//  native macOS. iOS builds are completely unaffected: every macOS-only
//  declaration below is wrapped in `#if os(macOS)`, and the cross-platform
//  helpers resolve to the exact same UIKit calls on iOS as before.

import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

// MARK: - Color components (cross-platform)

extension Color {
    /// sRGB components of the color. Uses UIKit on iOS and AppKit on macOS so
    /// the same call site works on both platforms.
    var rgbaComponents: (red: CGFloat, green: CGFloat, blue: CGFloat, alpha: CGFloat) {
        #if canImport(UIKit)
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(self).getRed(&r, green: &g, blue: &b, alpha: &a)
        return (r, g, b, a)
        #elseif canImport(AppKit)
        let ns = NSColor(self).usingColorSpace(.sRGB) ?? NSColor.black
        return (ns.redComponent, ns.greenComponent, ns.blueComponent, ns.alphaComponent)
        #else
        return (0, 0, 0, 1)
        #endif
    }
}

// MARK: - Color ↔ hex string (AppStorage / RawRepresentable)

extension Color: @retroactive RawRepresentable {
    /// Initialises a color from a 6-digit hex string such as `"#E61A1A"`.
    public init?(rawValue: String) {
        var str = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if str.hasPrefix("#") { str = String(str.dropFirst()) }
        guard str.count == 6, let val = UInt64(str, radix: 16) else { return nil }
        self.init(
            red:   Double((val >> 16) & 0xFF) / 255.0,
            green: Double((val >>  8) & 0xFF) / 255.0,
            blue:  Double( val        & 0xFF) / 255.0
        )
    }

    /// Returns the color as a 6-digit hex string such as `"#E61A1A"`.
    public var rawValue: String {
        let c = rgbaComponents
        return String(format: "#%02X%02X%02X",
                      Int((c.red   * 255).rounded()),
                      Int((c.green * 255).rounded()),
                      Int((c.blue  * 255).rounded()))
    }
}

// MARK: - Color interpolation

extension Color {
    /// Linearly interpolates between `self` (t = 0) and `other` (t = 1) in sRGB space.
    func interpolated(to other: Color, t: Double) -> Color {
        let a = rgbaComponents
        let b = other.rgbaComponents
        return Color(
            red:   Double(a.red)   + (Double(b.red)   - Double(a.red))   * t,
            green: Double(a.green) + (Double(b.green) - Double(a.green)) * t,
            blue:  Double(a.blue)  + (Double(b.blue)  - Double(a.blue))  * t
        )
    }
}

// MARK: - Toolbar placement (cross-platform)

extension ToolbarItemPlacement {
    /// Leading bar placement. Maps to the iOS navigation-bar leading slot and
    /// to `.automatic` on macOS, where that placement is unavailable.
    static var barLeading: ToolbarItemPlacement {
        #if os(iOS)
        .navigationBarLeading
        #else
        .automatic
        #endif
    }

    /// Bottom bar placement. Maps to the iOS bottom toolbar and to `.automatic`
    /// on macOS, where that placement is unavailable.
    static var barBottom: ToolbarItemPlacement {
        #if os(iOS)
        .bottomBar
        #else
        .automatic
        #endif
    }
}

extension View {
    /// Hides the navigation bar on iOS; a no-op on macOS where there is none.
    func barHidden(_ hidden: Bool = true) -> some View {
        #if os(iOS)
        navigationBarHidden(hidden)
        #else
        self
        #endif
    }
}

#if os(macOS)

// MARK: - Text-input modifiers (no-ops on macOS)

/// Stand-in for SwiftUI's iOS-only `TextInputAutocapitalization`.
enum TextInputAutocapitalization {
    case never, words, sentences, characters
}

/// Stand-in for UIKit's `UIKeyboardType` (irrelevant on macOS hardware keyboards).
enum UIKeyboardType {
    case `default`, asciiCapable, numbersAndPunctuation, URL, numberPad
    case phonePad, namePhonePad, emailAddress, decimalPad, twitter, webSearch
    case asciiCapableNumberPad
}

extension View {
    /// No-op on macOS — capitalization is governed by the system.
    func textInputAutocapitalization(_ autocapitalization: TextInputAutocapitalization) -> some View { self }

    /// No-op on macOS — there is no software keyboard to configure.
    func keyboardType(_ type: UIKeyboardType) -> some View { self }
}

// MARK: - Navigation bar title display mode (no-op on macOS)

/// Stand-in for SwiftUI's iOS-only `NavigationBarItem.TitleDisplayMode`.
enum NavigationBarItemTitleDisplayMode { case automatic, inline, large }

extension View {
    /// No-op on macOS — the Mac has no navigation-bar title chrome.
    func navigationBarTitleDisplayMode(_ mode: NavigationBarItemTitleDisplayMode) -> some View { self }
}

// MARK: - UIKit semantic system colors → AppKit equivalents

/// Stand-in for the UIKit semantic `UIColor`s used as `Color(.xxx)` throughout
/// the iOS UI. Maps each to the closest AppKit system color so the call sites
/// (`Color(.secondarySystemGroupedBackground)`, etc.) compile unchanged.
enum UIKitSemanticColor {
    case systemBackground
    case secondarySystemBackground
    case systemGroupedBackground
    case secondarySystemGroupedBackground
    case separator
    case placeholderText

    var color: Color {
        switch self {
        case .systemBackground:                 return Color(nsColor: .textBackgroundColor)
        case .secondarySystemBackground:        return Color(nsColor: .windowBackgroundColor)
        case .systemGroupedBackground:          return Color(nsColor: .windowBackgroundColor)
        case .secondarySystemGroupedBackground: return Color(nsColor: .controlBackgroundColor)
        case .separator:                        return Color(nsColor: .separatorColor)
        case .placeholderText:                  return Color(nsColor: .placeholderTextColor)
        }
    }
}

extension Color {
    init(_ semantic: UIKitSemanticColor) { self = semantic.color }
}

// MARK: - SwiftUI view → multipage PDF (vector, headless)

/// Renders one or more SwiftUI views into a vector PDF using Core Graphics.
/// Each entry becomes one PDF page sized to its `CGSize`. Works without a
/// window, so it is safe to call for off-screen export.
@MainActor
func renderViewsToPDF<V: View>(_ pages: [(ImageRenderer<V>, CGSize)]) -> Data? {
    guard !pages.isEmpty else { return nil }
    let data = NSMutableData()
    guard let consumer = CGDataConsumer(data: data as CFMutableData) else { return nil }
    var firstBox = CGRect(origin: .zero, size: pages[0].1)
    guard let ctx = CGContext(consumer: consumer, mediaBox: &firstBox, nil) else { return nil }
    for (renderer, size) in pages {
        var box = CGRect(origin: .zero, size: size)
        let info = [kCGPDFContextMediaBox: Data(bytes: &box, count: MemoryLayout<CGRect>.size)] as CFDictionary
        renderer.render { _, render in
            ctx.beginPDFPage(info)
            render(ctx)
            ctx.endPDFPage()
        }
    }
    ctx.closePDF()
    return data as Data
}

// MARK: - Presentation

extension View {
    /// macOS has no full-screen cover; present the content as a sheet instead.
    func fullScreenCover<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        sheet(isPresented: isPresented, onDismiss: onDismiss, content: content)
    }
}

#endif
