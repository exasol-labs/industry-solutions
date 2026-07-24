import Foundation

struct LLMService {

    static func chat(serverURL: String, apiKey: String, model: String, prompt: String) async throws -> String {
        guard let base = URL(string: serverURL.trimmingCharacters(in: .whitespaces)) else {
            throw URLError(.badURL)
        }
        let url = base.appendingPathComponent("chat/completions")

        var request = URLRequest(url: url, timeoutInterval: 180)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let trimmedKey = apiKey.trimmingCharacters(in: .whitespaces)
        if !trimmedKey.isEmpty {
            request.setValue("Bearer \(trimmedKey)", forHTTPHeaderField: "Authorization")
        }

        let body: [String: Any] = [
            "model":    model,
            "messages": [["role": "user", "content": prompt]],
            "stream":   false
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        if let http = response as? HTTPURLResponse, http.statusCode >= 400 {
            let msg = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw NSError(domain: "LLM", code: http.statusCode,
                          userInfo: [NSLocalizedDescriptionKey: msg])
        }

        guard let json     = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let choices  = json["choices"]  as? [[String: Any]],
              let first    = choices.first,
              let message  = first["message"] as? [String: Any],
              let content  = message["content"] as? String
        else { throw URLError(.cannotParseResponse) }

        // Strip <think>…</think> reasoning blocks some models prepend
        let stripped = content
            .replacingOccurrences(of: "<think>[\\s\\S]*?</think>",
                                  with: "",
                                  options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return stripped.isEmpty ? content : stripped
    }
}
