import SwiftUI

// MARK: - Shape enum

enum StepShape: String, CaseIterable, Identifiable {
    case stadium = "stadium"
    case round   = "round"
    case hex     = "hex"
    case circle  = "circle"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .stadium: return "Stadium"
        case .round:   return "Rounded"
        case .hex:     return "Hexagon"
        case .circle:  return "Circle"
        }
    }

    var icon: String {
        switch self {
        case .stadium: return "capsule"
        case .round:   return "rectangle.roundedcorner"
        case .hex:     return "hexagon"
        case .circle:  return "circle"
        }
    }
}

// MARK: - Step editor

struct StepEditorView: View {
    @ObservedObject var vm: AppViewModel

    @State private var selectedStep: String?  = nil
    @State private var bgColor:  Color        = .blue
    @State private var fgColor:  Color        = .white
    @State private var score:    Int          = 0
    @State private var hasScore: Bool         = false
    @State private var shape:    StepShape    = .stadium
    @State private var belongsTo: String      = ""
    @State private var description: String    = ""
    @State private var isSaving: Bool         = false
    @State private var saveError: String?     = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            stepPicker

            if selectedStep != nil {
                Divider()
                colorRow
                scoreRow
                shapeGrid
                groupRow
                descriptionRow
                Divider()
                saveRow
            }
        }
        .onChange(of: selectedStep) { _, step in loadValues(for: step) }
        .onChange(of: vm.selectedProject?.projectId) { _, _ in selectedStep = nil }
    }

    // MARK: Step picker

    private var stepPicker: some View {
        HStack {
            Text("Step")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .leading)

            Menu {
                Button("— None —") { selectedStep = nil }
                Divider()
                ForEach(vm.allSteps, id: \.self) { s in
                    Button(s) { selectedStep = s }
                }
            } label: {
                HStack(spacing: 6) {
                    Text(selectedStep ?? "Select a step")
                        .font(.caption)
                        .foregroundStyle(selectedStep == nil ? .secondary : .primary)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 7)
                    .fill(Color.secondary.opacity(0.10)))
            }
            .disabled(vm.allSteps.isEmpty)
        }
    }

    // MARK: Colours

    private var colorRow: some View {
        HStack(spacing: 0) {
            Text("Colors")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .leading)

            HStack(spacing: 14) {
                VStack(spacing: 3) {
                    ColorPicker("", selection: $bgColor, supportsOpacity: false)
                        .labelsHidden()
                        .frame(width: 34, height: 28)
                    Text("BG").font(.caption2).foregroundStyle(.secondary)
                }
                VStack(spacing: 3) {
                    ColorPicker("", selection: $fgColor, supportsOpacity: false)
                        .labelsHidden()
                        .frame(width: 34, height: 28)
                    Text("FG").font(.caption2).foregroundStyle(.secondary)
                }

                // Live preview chip
                Spacer(minLength: 0)
                RoundedRectangle(cornerRadius: 8)
                    .fill(bgColor)
                    .frame(height: 32)
                    .overlay(
                        Text(selectedStep ?? "Step")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(fgColor)
                            .lineLimit(1)
                            .minimumScaleFactor(0.6)
                            .padding(.horizontal, 8)
                    )
                    .frame(maxWidth: 100)
            }
        }
    }

    // MARK: Score

    private var scoreRow: some View {
        HStack(spacing: 8) {
            Text("Score")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .leading)

            Toggle("", isOn: $hasScore)
                .labelsHidden()
                .controlSize(.small)
                .frame(width: 38)

            if hasScore {
                HStack(spacing: 4) {
                    TextField("0", value: $score, format: .number)
                        .keyboardType(.numbersAndPunctuation)
                        .font(.caption.monospacedDigit())
                        .multilineTextAlignment(.center)
                        .frame(width: 52)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 4)
                        .background(RoundedRectangle(cornerRadius: 6)
                            .fill(Color.secondary.opacity(0.10)))
                    Stepper("", value: $score, in: -999...999)
                        .labelsHidden()
                        .controlSize(.small)
                }
            } else {
                Text("None").font(.caption).foregroundStyle(.tertiary)
            }
        }
    }

    // MARK: Shape grid

    private var shapeGrid: some View {
        HStack(alignment: .top, spacing: 0) {
            Text("Shape")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .leading)
                .padding(.top, 5)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 6) {
                ForEach(StepShape.allCases) { s in
                    Button { shape = s } label: {
                        HStack(spacing: 5) {
                            Image(systemName: s.icon).font(.caption2)
                            Text(s.displayName).font(.system(size: 11)).lineLimit(1)
                        }
                        .padding(.horizontal, 6)
                        .padding(.vertical, 6)
                        .frame(maxWidth: .infinity)
                        .background(
                            RoundedRectangle(cornerRadius: 7)
                                .fill(shape == s
                                      ? Color.accentColor.opacity(0.15)
                                      : Color.secondary.opacity(0.08))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 7)
                                .strokeBorder(shape == s
                                              ? Color.accentColor.opacity(0.6)
                                              : Color.clear, lineWidth: 1)
                        )
                        .foregroundStyle(shape == s ? Color.accentColor : Color.primary)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    // MARK: Group (BELONGS_TO)

    private var groupRow: some View {
        HStack {
            Text("Group")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .leading)

            TextField("BELONGS_TO", text: $belongsTo)
                .font(.caption)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.characters)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 6)
                    .fill(Color.secondary.opacity(0.10)))
        }
    }

    // MARK: Description

    private var descriptionRow: some View {
        HStack(alignment: .top) {
            Text("Note")
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .leading)
                .padding(.top, 5)

            TextField("Node description", text: $description, axis: .vertical)
                .font(.caption)
                .lineLimit(3, reservesSpace: false)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.sentences)
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 6)
                    .fill(Color.secondary.opacity(0.10)))
        }
    }

    // MARK: Save

    private var saveRow: some View {
        VStack(alignment: .trailing, spacing: 4) {
            if let error = saveError {
                Text(error)
                    .font(.caption2)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            Button {
                Task { await save() }
            } label: {
                HStack(spacing: 6) {
                    if isSaving { ProgressView().controlSize(.mini) }
                    Text("Save")
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .disabled(selectedStep == nil || isSaving)
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
    }

    // MARK: Logic

    private func loadValues(for stepName: String?) {
        saveError = nil
        guard let stepName, let info = vm.allStepInfos[stepName] else { return }
        bgColor     = Color.named(info.bgColor)
        fgColor     = Color.named(info.fgColor)
        if let s = info.score { score = s; hasScore = true }
        else { score = 0; hasScore = false }
        shape       = StepShape(rawValue: info.shape) ?? .stadium
        belongsTo   = info.belongsTo ?? ""
        description = info.description == stepName ? "" : info.description
    }

    private func save() async {
        guard let step = selectedStep,
              let projectId = vm.selectedProject?.projectId else { return }
        isSaving  = true
        saveError = nil
        defer { isSaving = false }
        await vm.updateStep(
            projectId:   projectId, step: step,
            bgColor:     bgColor.hexString,
            fgColor:     fgColor.hexString,
            score:       hasScore ? score : nil,
            shape:       shape.rawValue,
            belongsTo:   belongsTo.isEmpty ? nil : belongsTo,
            description: description.isEmpty ? nil : description
        )
        if let err = vm.errorMessage { saveError = err }
    }
}
