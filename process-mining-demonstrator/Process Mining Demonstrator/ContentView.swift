import SwiftUI
import LocalAuthentication
import UniformTypeIdentifiers

struct ContentView: View {
    @StateObject private var vm = AppViewModel()
    @State private var selectedProjectId: String?
    @State private var showHelp  = false
    @State private var activeAlert: AppAlert?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @AppStorage("app.theme")                  private var appTheme             = "system"
    @AppStorage("legal.accepted")             private var legalAccepted        = false
    @AppStorage("security.requireAuthentication") private var requireAuthentication = false
    @State private var isLocked              = false
    @State private var showLaunchSplash      = true
    @Environment(\.scenePhase)               private var scenePhase

    private var preferredScheme: ColorScheme? {
        switch appTheme {
        case "light": return .light
        case "dark":  return .dark
        default:      return nil
        }
    }

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView(vm: vm, selectedProjectId: $selectedProjectId,
                        columnVisibility: $columnVisibility)
                .navigationSplitViewColumnWidth(min: 240, ideal: 340, max: 340)
        } detail: {
            ProcessMapView(vm: vm)
        }
        .focusedSceneValue(\.showHelp, $showHelp)
        .onChange(of: selectedProjectId) { _, id in
            guard let id,
                  let project = vm.projects.first(where: { $0.projectId == id }) else { return }
            Task { await vm.selectProject(project) }
        }
        .task {
            if DatabaseManager.shared.isConnected { await vm.loadProjects() }
        }
        .overlay {
            if showHelp {
                GeometryReader { geo in
                    FloatingHelpPanel(isPresented: $showHelp, container: geo.size)
                }
                .ignoresSafeArea()
            }
        }
        // Show sidebar button when panel is collapsed
        .overlay(alignment: .topLeading) {
            if columnVisibility == .detailOnly {
                Button {
                    withAnimation(.easeInOut(duration: 0.25)) { columnVisibility = .all }
                } label: {
                    Image(systemName: "sidebar.left")
                        .font(.body.weight(.medium))
                        .foregroundStyle(.secondary)
                        .padding(10)
                        .background(.regularMaterial,
                                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .shadow(color: .black.opacity(0.18), radius: 6, y: 2)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Show Sidebar")
                .padding(.leading, 16)
                .padding(.top, 14)
                .transition(.opacity.combined(with: .scale(scale: 0.8, anchor: .topLeading)))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: columnVisibility)
        .modifier(AppAlertModifier(vm: vm, activeAlert: $activeAlert))
        .preferredColorScheme(preferredScheme)
        .fullScreenCover(isPresented: Binding(
            get: { !legalAccepted },
            set: { if !$0 { legalAccepted = true } }
        )) {
            LegalDisclaimerView { legalAccepted = true }
        }
        // Splash screen — shown as an overlay on launch so it is always visible
        .overlay {
            if showLaunchSplash {
                ZStack {
                    Color.black.opacity(0.25)
                        .ignoresSafeArea()
                    SplashScreenView(autoClose: true) {
                        withAnimation(.easeOut(duration: 0.3)) {
                            showLaunchSplash = false
                        }
                    }
                    .background(.regularMaterial,
                                in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .shadow(color: .black.opacity(0.25), radius: 40, y: 12)
                }
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.3), value: showLaunchSplash)
        // Lock screen overlay — sits above splash, below the legal gate
        .overlay {
            if isLocked && requireAuthentication {
                AppLockView { Task { await authenticate() } }
                    .ignoresSafeArea()
                    .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.2), value: isLocked)
        // Lock when backgrounded; auto-authenticate when returning to foreground
        .onChange(of: scenePhase) { _, phase in
            guard requireAuthentication else { return }
            if phase == .background {
                isLocked = true
            } else if phase == .active && isLocked {
                Task { await authenticate() }
            }
        }
        // Lock and authenticate on cold launch
        .task {
            guard requireAuthentication else { return }
            isLocked = true
            await authenticate()
        }
    }

    private func authenticate() async {
        let ctx = LAContext()
        var error: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            // No passcode / biometrics configured on this device — unlock silently
            isLocked = false
            return
        }
        do {
            let ok = try await ctx.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: "Unlock Process Mining Demonstrator"
            )
            if ok { isLocked = false }
        } catch {
            // Auth cancelled or failed — stay locked; user can tap the button to retry
        }
    }
}

// MARK: - Alert modifier

private struct AppAlertModifier: ViewModifier {
    @ObservedObject var db = DatabaseManager.shared
    @ObservedObject var vm: AppViewModel
    @Binding var activeAlert: AppAlert?

    func body(content: Content) -> some View {
        content
            .onChange(of: db.pendingAlert?.id) { _, _ in
                if let alert = db.pendingAlert { activeAlert = alert }
            }
            .onChange(of: vm.pendingAlert?.id) { _, _ in
                if let alert = vm.pendingAlert { activeAlert = alert }
            }
            .alert(item: $activeAlert) { (alert: AppAlert) -> Alert in
                if let sec = alert.secondary {
                    return Alert(
                        title: Text(alert.title),
                        message: Text(alert.message),
                        primaryButton: .default(Text(alert.primary.label)) { alert.primary.action?() },
                        secondaryButton: sec.role == .cancel
                            ? .cancel(Text(sec.label)) { sec.action?() }
                            : .default(Text(sec.label)) { sec.action?() }
                    )
                }
                return Alert(
                    title: Text(alert.title),
                    message: Text(alert.message),
                    dismissButton: .default(Text(alert.primary.label)) { alert.primary.action?() }
                )
            }
    }
}

// MARK: - Floating help panel

private struct FloatingHelpPanel: View {
    @Binding var isPresented: Bool
    let container: CGSize

    // Panel geometry
    @State private var position: CGPoint? = nil   // nil → auto-positioned on appear
    @State private var size = CGSize(width: 460, height: 580)

    // Live gesture offsets
    @GestureState private var moveDelta  = CGSize.zero
    @GestureState private var resizeDelta = CGSize.zero

    // PDF export
    @State private var isExporting     = false
    @State private var showExporter    = false
    @State private var exportDocument: HelpPDFDocument?

    private let minSize = CGSize(width: 300, height: 280)

    private var currentSize: CGSize {
        CGSize(
            width:  max(minSize.width,  size.width  + resizeDelta.width),
            height: max(minSize.height, size.height + resizeDelta.height)
        )
    }

    private var currentPos: CGPoint {
        let base = position ?? defaultPosition
        return clamped(
            CGPoint(x: base.x + moveDelta.width, y: base.y + moveDelta.height),
            size: currentSize
        )
    }

    private var defaultPosition: CGPoint {
        CGPoint(x: container.width * 0.65, y: container.height * 0.45)
    }

    var body: some View {
        VStack(spacing: 0) {
            titleBar
            Divider()
            HelpView(onDismiss: { isPresented = false })
        }
        .frame(width: currentSize.width, height: currentSize.height)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5)
        )
        .shadow(color: .black.opacity(0.28), radius: 40, x: 0, y: 12)
        .overlay(alignment: .bottomTrailing) { resizeHandle }
        .position(currentPos)
        .onAppear {
            if position == nil { position = defaultPosition }
        }
        .fileExporter(
            isPresented: $showExporter,
            document: exportDocument,
            contentType: .pdf,
            defaultFilename: "Process Mining Demonstrator Help"
        ) { _ in
            exportDocument = nil
        }
    }

    // MARK: PDF export

    /// Renders the help document to PDF data (no print system involved, so it
    /// works in the sandboxed macOS app) and presents a native Save panel.
    @MainActor
    private func exportPDF() async {
        guard !isExporting else { return }
        isExporting = true
        defer { isExporting = false }
        guard let data = await HelpView.generatePDFData() else { return }
        exportDocument = HelpPDFDocument(data: data)
        showExporter = true
    }

    // MARK: Title bar (drag to move)

    private var titleBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "questionmark.circle.fill")
                .foregroundStyle(Color.accentColor)
                .font(.body)

            Text("Help")
                .font(.headline)

            Spacer(minLength: 0)

            Button {
                Task { await exportPDF() }
            } label: {
                Group {
                    if isExporting {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "square.and.arrow.up")
                            .font(.title3)
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(isExporting)
            .accessibilityLabel("Export Help as PDF")
            .help("Export help as PDF")

            Button { isPresented = false } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close Help")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color.primary.opacity(0.04))
        .contentShape(Rectangle())
        .gesture(
            DragGesture()
                .updating($moveDelta) { value, state, _ in
                    state = value.translation
                }
                .onEnded { value in
                    let base = position ?? defaultPosition
                    let moved = CGPoint(
                        x: base.x + value.translation.width,
                        y: base.y + value.translation.height
                    )
                    position = clamped(moved, size: currentSize)
                }
        )
    }

    // MARK: Resize handle (drag bottom-right corner)

    private var resizeHandle: some View {
        Image(systemName: "arrow.up.left.and.arrow.down.right")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.tertiary)
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .accessibilityLabel("Resize panel")
            .gesture(
                DragGesture()
                    .updating($resizeDelta) { value, state, _ in
                        state = value.translation
                    }
                    .onEnded { value in
                        size = CGSize(
                            width:  max(minSize.width,  size.width  + value.translation.width),
                            height: max(minSize.height, size.height + value.translation.height)
                        )
                    }
            )
            .padding(6)
    }

    // MARK: Keep panel within container bounds

    private func clamped(_ p: CGPoint, size: CGSize) -> CGPoint {
        let halfW = size.width  / 2
        let halfH = size.height / 2
        return CGPoint(
            x: max(halfW, min(container.width  - halfW, p.x)),
            y: max(halfH, min(container.height - halfH, p.y))
        )
    }
}

// MARK: - Help PDF document (for .fileExporter)

/// Lightweight `FileDocument` wrapping already-rendered PDF data so the help
/// panel can offer a native "Save…" panel via `.fileExporter`.
struct HelpPDFDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.pdf] }
    static var writableContentTypes: [UTType] { [.pdf] }

    let data: Data

    init(data: Data) { self.data = data }

    init(configuration: ReadConfiguration) throws {
        data = configuration.file.regularFileContents ?? Data()
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }
}

// MARK: - Legal Disclaimer (first-launch gate)

private struct LegalDisclaimerView: View {
    let onAccept: () -> Void
    @State private var accepted = false

    var body: some View {
        VStack(spacing: 0) {
            // Header
            VStack(spacing: 6) {
                Image(systemName: "exclamationmark.octagon.fill")
                    .font(.system(size: 40))
                    .foregroundStyle(.red)
                Text("Legal Disclaimer")
                    .font(.title2.weight(.bold))
                Text("Please read carefully before continuing")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding(.top, 40)
            .padding(.bottom, 24)

            Divider()

            // Scrollable disclaimer text
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    disclaimerSection(
                        heading: "Purpose and scope",
                        body: "This application is provided for educational and exploratory purposes only. Any productive or business-critical use is the sole responsibility of the user."
                    )

                    disclaimerSection(
                        heading: "AI-generated results",
                        body: "Process Mining Demonstrator includes AI-powered analysis features that use large language models to interpret process data. AI models can produce results that are incorrect, incomplete, or misleading.\n\nNeither the author of this application nor Exasol SE (the database vendor) accepts any liability whatsoever for decisions, conclusions, or actions taken on the basis of AI-generated results. You must independently verify every AI finding before acting on it."
                    )

                    disclaimerSection(
                        heading: "Data accuracy",
                        body: "Process maps, KPIs, journey statistics, and all other computed results depend entirely on the quality, completeness, and correctness of the data stored in your Exasol database. Neither the author nor Exasol SE accepts any liability for incorrect or misleading results arising from incomplete, erroneous, or misinterpreted source data."
                    )

                    disclaimerSection(
                        heading: "Limitation of liability",
                        body: "To the fullest extent permitted by applicable law, the author and Exasol SE expressly disclaim all warranties, express or implied, including but not limited to fitness for a particular purpose, accuracy, and non-infringement.\n\nIn no event shall the author or Exasol SE be liable for any direct, indirect, incidental, special, or consequential damages arising from the use of, or inability to use, this application or its outputs."
                    )

                    // Device-transfer notice
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Device transfer", systemImage: "ipad.and.iphone")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.orange)
                        Text("Acceptance of this disclaimer is recorded on this device. If this device is handed to another person — for example a shared iPad — the obligation to comply with these terms and the acknowledgement of their content passes automatically to the new user. The new user is bound by these terms from the moment they first operate the application.")
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                    }
                    .padding(14)
                    .background(Color.orange.opacity(0.08),
                                in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .strokeBorder(Color.orange.opacity(0.30), lineWidth: 1)
                    )
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 20)
            }

            Divider()

            // Acknowledgement row + Accept button
            VStack(spacing: 14) {
                Toggle(isOn: $accepted) {
                    Text("I have read and accept all terms stated above")
                        .font(.subheadline)
                }
                .toggleStyle(.switch)
                .padding(.horizontal, 24)

                Button {
                    onAccept()
                } label: {
                    Text("Accept & Continue")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(accepted ? Color.accentColor : Color.secondary.opacity(0.25),
                                    in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .foregroundStyle(accepted ? Color.white : Color.secondary)
                }
                .buttonStyle(.plain)
                .disabled(!accepted)
                .padding(.horizontal, 24)
                .animation(.easeInOut(duration: 0.15), value: accepted)
            }
            .padding(.vertical, 20)
            .background(Color(.systemGroupedBackground))
        }
        .background(Color(.systemGroupedBackground).ignoresSafeArea())
        .interactiveDismissDisabled(true)
    }

    @ViewBuilder
    private func disclaimerSection(heading: String, body: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(heading)
                .font(.subheadline.weight(.semibold))
            Text(body)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
}

// MARK: - App lock screen

private struct AppLockView: View {
    let onUnlock: () -> Void

    // Resolve the best available biometry label and icon at draw time
    private var biometryInfo: (label: String, icon: String) {
        let ctx = LAContext()
        var err: NSError?
        ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &err)
        switch ctx.biometryType {
        case .faceID:   return ("Face ID",   "faceid")
        case .touchID:  return ("Touch ID",  "touchid")
        default:        return ("Passcode",  "lock.fill")
        }
    }

    var body: some View {
        ZStack {
            // Blurred backdrop — hides app content behind the lock screen
            Rectangle()
                .fill(.ultraThinMaterial)
                .ignoresSafeArea()

            VStack(spacing: 32) {
                Spacer()

                // App icon area
                VStack(spacing: 16) {
                    Image(systemName: "lock.shield.fill")
                        .font(.system(size: 64))
                        .foregroundStyle(Color.accentColor)
                        .symbolRenderingMode(.hierarchical)

                    Text("Process Mining Demonstrator is Locked")
                        .font(.title2.weight(.bold))

                    Text("Authentication required to access your data.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 280)
                }

                Spacer()

                // Unlock button
                Button {
                    onUnlock()
                } label: {
                    Label(biometryInfo.label, systemImage: biometryInfo.icon)
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.accentColor,
                                    in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .foregroundStyle(Color.white)
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 40)
                .padding(.bottom, 48)
            }
        }
        .onAppear { onUnlock() }
    }
}
