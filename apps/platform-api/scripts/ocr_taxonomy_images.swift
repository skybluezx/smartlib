import Foundation
import Vision
import ImageIO

// Headless Vision OCR. Retain positions and alternatives for source-level review.
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
let files = try FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)
for file in files.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) where file.pathExtension == "jpg" {
    let destination = output.appendingPathComponent(file.lastPathComponent + ".json")
    if FileManager.default.fileExists(atPath: destination.path) { continue }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = CommandLine.arguments.count > 3
    let handler = VNImageRequestHandler(url: file)
    try handler.perform([request])
    let rows: [[String: Any]] = (request.results ?? []).map { observation in
        let box = observation.boundingBox
        return ["text": observation.topCandidates(1).first?.string ?? "",
                "confidence": observation.topCandidates(1).first?.confidence ?? 0,
                "alternatives": observation.topCandidates(3).map { $0.string },
                "x": box.minX, "y": box.minY, "width": box.width, "height": box.height]
    }
    let data = try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: destination)
    print("\(file.lastPathComponent): \(rows.count) text regions")
}
