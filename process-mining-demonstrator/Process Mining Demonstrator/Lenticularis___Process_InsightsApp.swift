import SwiftUI

@main
struct LenticularisApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .commands {
            HelpCommands()
            AboutCommands()
        }

        Settings {
            PreferencesView()
        }

        Window("About Process Mining Demonstrator", id: "about") {
            SplashScreenView(autoClose: false)
        }
        .windowResizability(.contentSize)
    }
}

// MARK: - About menu

private struct AboutCommands: Commands {
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .appInfo) {
            Button("About Process Mining Demonstrator…") {
                openWindow(id: "about")
            }
        }
    }
}

// MARK: - Help menu

/// Replaces the standard Help menu with an entry that opens the app's
/// in-app help panel. The command reads the focused scene's `showHelp`
/// binding, which `ContentView` publishes via `focusedSceneValue`.
private struct HelpCommands: Commands {
    @FocusedBinding(\.showHelp) private var showHelp

    var body: some Commands {
        CommandGroup(replacing: .help) {
            Button("Process Mining Demonstrator Help") {
                showHelp = true
            }
            .keyboardShortcut("?", modifiers: .command)
            .disabled(showHelp == nil)
        }
    }
}

// MARK: - Focused value plumbing

private struct ShowHelpKey: FocusedValueKey {
    typealias Value = Binding<Bool>
}

extension FocusedValues {
    /// Binding to the active scene's in-app help visibility, surfaced so menu
    /// commands can toggle it.
    var showHelp: Binding<Bool>? {
        get { self[ShowHelpKey.self] }
        set { self[ShowHelpKey.self] = newValue }
    }
}
