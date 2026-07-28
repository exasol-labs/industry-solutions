import SwiftUI

struct SplashScreenView: View {
    /// When true, shows a countdown and auto-closes after 5 s (launch splash).
    /// When false, only a Close button is shown (About menu).
    var autoClose: Bool = false
    /// Callback used when the view is hosted as an overlay (launch splash).
    /// Nil when hosted in a Window scene — dismiss() is used instead.
    var onClose: (() -> Void)? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var countdown = 5

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "chart.bar.xaxis.ascending")
                .font(.system(size: 72))
                .foregroundStyle(Color.accentColor)
                .symbolRenderingMode(.hierarchical)
                .padding(.top, 8)

            VStack(spacing: 4) {
                Text("Process Mining")
                    .font(.largeTitle.weight(.bold))
                Text("Demonstrator")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }

            Divider().frame(maxWidth: 160)

            VStack(spacing: 4) {
                Text("Version 0.75")
                    .font(.headline)
                Text("by Dirk Beerbohm")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 10) {
                Label("Demo & Educational Use Only", systemImage: "exclamationmark.circle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text("This application is provided for demonstration and educational purposes only. It is not intended for production or business-critical use. Any results, analyses, or conclusions drawn from this application must be independently verified before being relied upon.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(14)
            .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(Color.orange.opacity(0.30), lineWidth: 1)
            )

            HStack {
                if autoClose && countdown > 0 {
                    Text("Closing in \(countdown)s…")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .monospacedDigit()
                }
                Spacer()
                Button("Close") { close() }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
            .padding(.bottom, 8)
        }
        .padding(32)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
        .task {
            guard autoClose else { return }
            for remaining in stride(from: 4, through: 0, by: -1) {
                try? await Task.sleep(for: .seconds(1))
                countdown = remaining
            }
            close()
        }
    }

    private func close() {
        if let onClose { onClose() }
        else { dismiss() }
    }
}
