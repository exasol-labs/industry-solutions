import SwiftUI
import UniformTypeIdentifiers
#if canImport(AppKit)
import AppKit
#endif

#if os(iOS)
// Presents UIActivityViewController on the window's root VC, avoiding the white-sheet issue.
private struct ActivityPresenter: UIViewControllerRepresentable {
    let url: URL
    @Binding var isPresented: Bool

    class Coordinator { var hasPresented = false }
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIViewController(context: Context) -> UIViewController { UIViewController() }

    func updateUIViewController(_ vc: UIViewController, context: Context) {
        guard isPresented, !context.coordinator.hasPresented else { return }
        context.coordinator.hasPresented = true
        let av = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        av.completionWithItemsHandler = { _, _, _, _ in
            DispatchQueue.main.async {
                isPresented = false
                context.coordinator.hasPresented = false
            }
        }
        DispatchQueue.main.async {
            guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                  let root  = scene.windows.first(where: { $0.isKeyWindow })?.rootViewController
            else { return }
            var top = root
            while let next = top.presentedViewController { top = next }
            top.present(av, animated: true)
        }
    }
}
#else
// macOS shares via NSSharingServicePicker, anchored to the host view.
private struct ActivityPresenter: NSViewRepresentable {
    let url: URL
    @Binding var isPresented: Bool

    func makeNSView(context: Context) -> NSView { NSView() }

    func updateNSView(_ nsView: NSView, context: Context) {
        guard isPresented, !context.coordinator.hasPresented else { return }
        context.coordinator.hasPresented = true
        DispatchQueue.main.async {
            let picker = NSSharingServicePicker(items: [url])
            let anchor = nsView.bounds.isEmpty ? CGRect(x: 0, y: 0, width: 1, height: 1) : nsView.bounds
            picker.show(relativeTo: anchor, of: nsView, preferredEdge: .minY)
            isPresented = false
            context.coordinator.hasPresented = false
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var hasPresented = false }
}
#endif

struct BackupRestoreView: View {
    @Environment(\.dismiss) private var dismiss

    // Export
    @State private var includePasswords       = false
    @State private var includeUsername        = true
    @State private var includeLlmApiKey       = false
    @State private var passwordProtect        = false
    @State private var exportPassword         = ""
    @State private var exportPasswordConfirm  = ""
    @State private var exportURL: URL?
    @State private var showShareSheet         = false
    @State private var exportError: String?

    // Import
    @State private var showFilePicker         = false
    @State private var rawImportData: Data?          // holds encrypted bytes pending password
    @State private var showDecryptPrompt      = false
    @State private var decryptPassword        = ""
    @State private var importedBackup: AppBackup?
    @State private var importError: String?
    @State private var showRestoreConfirm     = false
    @State private var restoreOptions         = RestoreOptions()

    private var exportPasswordsMatch: Bool {
        exportPassword == exportPasswordConfirm
    }
    private var exportReady: Bool {
        !passwordProtect || (!exportPassword.isEmpty && exportPasswordsMatch)
    }

    var body: some View {
        NavigationStack {
            Form {
                exportSection
                importSection
                if let backup = importedBackup {
                    previewSection(backup.summary)
                    restoreOptionsSection(backup.summary)
                    restoreSection
                }
            }
            .formStyle(.grouped)
            .navigationTitle("Backup & Restore")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
            #if os(macOS)
            .frame(minWidth: 540, idealWidth: 560, minHeight: 620, idealHeight: 680)
            #endif
        }
        .background(Group {
            if showShareSheet, let url = exportURL {
                ActivityPresenter(url: url, isPresented: $showShareSheet)
            }
        })
        .fileImporter(
            isPresented: $showFilePicker,
            allowedContentTypes: [.json],
            allowsMultipleSelection: false
        ) { result in
            handleImport(result)
        }
        .alert("Backup is Password Protected", isPresented: $showDecryptPrompt) {
            SecureField("Password", text: $decryptPassword)
            Button("Unlock") { attemptDecrypt() }
            Button("Cancel", role: .cancel) {
                rawImportData   = nil
                decryptPassword = ""
            }
        } message: {
            Text("Enter the password used when this backup was exported.")
        }
        .confirmationDialog(
            "Restore Backup?",
            isPresented: $showRestoreConfirm,
            titleVisibility: .visible
        ) {
            Button("Restore", role: .destructive) {
                if let backup = importedBackup {
                    BackupManager.apply(backup, options: restoreOptions)
                    dismiss()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will overwrite your current settings and merge connections. You may need to restart the app for all view state changes to take effect.")
        }
    }

    // MARK: Export

    private var exportSection: some View {
        Section {
            Toggle("Include database username", isOn: $includeUsername)
            Toggle("Include LLM API key",       isOn: $includeLlmApiKey)
            Toggle("Include passwords",          isOn: $includePasswords)

            Divider()

            Toggle("Encrypt backup file", isOn: $passwordProtect.animation())
            if passwordProtect {
                SecureField("Password", text: $exportPassword)
                    .textContentType(.newPassword)
                SecureField("Confirm password", text: $exportPasswordConfirm)
                    .textContentType(.newPassword)
                if !exportPassword.isEmpty && !exportPasswordConfirm.isEmpty && !exportPasswordsMatch {
                    Text("Passwords do not match.")
                        .font(.caption).foregroundStyle(.red)
                }
            }

            Button {
                doExport()
            } label: {
                Label("Export Backup\u{2026}", systemImage: "square.and.arrow.up")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!exportReady)

            if let err = exportError {
                Text(err).font(.caption).foregroundStyle(.red)
            }
        } header: {
            Text("Export")
        } footer: {
            Text("Exports connections, app settings, sidebar state, chart layouts, norms, happy path definitions, filter presets, and LLM prompt templates to a JSON file. Use the toggles to control which credentials are included. Enable 'Encrypt backup file' to AES-encrypt the file with a password before sharing. Process notes are stored in the database and are not included.")
        }
    }

    // MARK: Import

    private var importSection: some View {
        Section {
            Button {
                importedBackup  = nil
                importError     = nil
                showFilePicker  = true
            } label: {
                Label("Choose Backup File\u{2026}", systemImage: "square.and.arrow.down")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)

            if let err = importError {
                Text(err).font(.caption).foregroundStyle(.red)
            }
        } header: {
            Text("Import")
        } footer: {
            Text("Select a previously exported backup file. Password-protected files will prompt for the decryption password before the preview is shown.")
        }
    }

    // MARK: Preview

    private func previewSection(_ summary: AppBackup.Summary) -> some View {
        Section("Backup Preview") {
            LabeledContent("Created",          value: summary.createdAt.formatted(date: .abbreviated, time: .shortened))
            LabeledContent("Connections",      value: "\(summary.connectionCount)")
            LabeledContent("Projects",         value: "\(summary.projectCount)")
            LabeledContent("DB Username",      value: summary.includesUsername  ? "Included" : "Not included")
            LabeledContent("LLM API Key",      value: summary.includesLlmApiKey ? "Included" : "Not included")
            LabeledContent("Passwords",        value: summary.includesPasswords ? "Included" : "Not included")
            LabeledContent("Layouts",          value: summary.hasLayouts        ? "Yes" : "No")
            LabeledContent("Norms",            value: summary.hasNorms          ? "Yes" : "No")
            LabeledContent("Happy Paths",      value: summary.hasHappyPaths     ? "Yes" : "No")
            LabeledContent("Filter Presets",   value: summary.hasFilterGroups   ? "Yes" : "No")
        }
    }

    // MARK: Restore options

    private func restoreOptionsSection(_ summary: AppBackup.Summary) -> some View {
        Section {
            Toggle("App Settings & UI state", isOn: $restoreOptions.appSettings)

            if summary.connectionCount > 0 {
                Toggle("Connections", isOn: $restoreOptions.connections)
                if summary.includesUsername {
                    Toggle("Database Username", isOn: $restoreOptions.username)
                        .padding(.leading, 18)
                        .disabled(!restoreOptions.connections)
                }
                if summary.includesLlmApiKey {
                    Toggle("LLM API Key", isOn: $restoreOptions.llmApiKey)
                        .padding(.leading, 18)
                        .disabled(!restoreOptions.connections)
                }
                if summary.includesPasswords {
                    Toggle("Passwords", isOn: $restoreOptions.passwords)
                        .padding(.leading, 18)
                        .disabled(!restoreOptions.connections)
                }
            }
            if summary.hasLayouts    { Toggle("Chart Layouts",     isOn: $restoreOptions.layouts)       }
            if summary.hasNorms      { Toggle("Norms & AI Prompts", isOn: $restoreOptions.norms)        }
            if summary.hasHappyPaths { Toggle("Happy Paths",       isOn: $restoreOptions.happyPaths)    }
            if summary.hasFilterGroups { Toggle("Filter Presets",  isOn: $restoreOptions.filterPresets) }
        } header: {
            Text("Restore Options")
        } footer: {
            Text("Only sections present in the backup are shown. Indented toggles are disabled when their parent 'Connections' switch is off.")
        }
    }

    // MARK: Restore

    private var restoreSection: some View {
        Section {
            Button(role: .destructive) {
                showRestoreConfirm = true
            } label: {
                Label("Restore Backup\u{2026}", systemImage: "arrow.counterclockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(.red)
        } footer: {
            Text("Connections are merged by ID — connections not present in the backup are kept. Sections not selected above are left untouched.")
        }
    }

    // MARK: Actions

    private func doExport() {
        exportError = nil
        let backup = BackupManager.exportPayload(
            includePasswords: includePasswords,
            includeUsername:  includeUsername,
            includeLlmApiKey: includeLlmApiKey
        )
        do {
            var data = try BackupManager.encode(backup)
            if passwordProtect {
                data = try BackupManager.encryptBackup(data, password: exportPassword)
            }
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd"
            let name = "lenticularis-backup-\(formatter.string(from: Date())).json"
            let url  = FileManager.default.temporaryDirectory.appendingPathComponent(name)
            try data.write(to: url, options: .atomic)
            exportURL      = url
            showShareSheet = true
        } catch {
            exportError = error.localizedDescription
        }
    }

    private func handleImport(_ result: Result<[URL], Error>) {
        importError    = nil
        importedBackup = nil
        restoreOptions = RestoreOptions()
        switch result {
        case .failure(let err):
            importError = err.localizedDescription
        case .success(let urls):
            guard let url = urls.first else { return }
            do {
                let accessing = url.startAccessingSecurityScopedResource()
                defer { if accessing { url.stopAccessingSecurityScopedResource() } }
                let data = try Data(contentsOf: url)
                if BackupManager.isEncrypted(data) {
                    rawImportData     = data
                    decryptPassword   = ""
                    showDecryptPrompt = true
                } else {
                    importedBackup = try BackupManager.decode(from: data)
                }
            } catch {
                importError = "Could not read backup: \(error.localizedDescription)"
            }
        }
    }

    private func attemptDecrypt() {
        guard let data = rawImportData else { return }
        rawImportData = nil
        do {
            let plaintext  = try BackupManager.decryptBackup(data, password: decryptPassword)
            importedBackup = try BackupManager.decode(from: plaintext)
        } catch {
            importError = error.localizedDescription
        }
        decryptPassword = ""
    }
}
