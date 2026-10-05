// Read-only macOS 14.4+ system-output meter. No microphone, recording, or volume writes.
import Foundation
import CoreAudio

let schema = "system-audio.native-meter/v1"

func emit(_ value: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data + Data([10]))
}

func check(_ status: OSStatus, _ operation: String) throws {
    if status != noErr {
        throw NSError(domain: "SystemAudioMonitor", code: Int(status),
                      userInfo: [NSLocalizedDescriptionKey: "\(operation): CoreAudio \(status)"])
    }
}

func address(_ selector: AudioObjectPropertySelector,
             _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal,
             _ element: AudioObjectPropertyElement = kAudioObjectPropertyElementMain) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: element)
}

func defaultOutput() throws -> AudioObjectID {
    var property = address(kAudioHardwarePropertyDefaultOutputDevice)
    var device = AudioObjectID(0)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &property,
              0, nil, &size, &device), "Read default output device")
    guard device != kAudioObjectUnknown else {
        throw NSError(domain: "SystemAudioMonitor", code: 2,
                      userInfo: [NSLocalizedDescriptionKey: "No default output device"])
    }
    return device
}

func stringProperty(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector,
                    _ operation: String) throws -> String {
    var property = address(selector)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<CFString>.size)
    try check(AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value), operation)
    guard let value else {
        throw NSError(domain: "SystemAudioMonitor", code: 7,
                      userInfo: [NSLocalizedDescriptionKey: "\(operation): empty string"])
    }
    return value.takeUnretainedValue() as String
}

func sampleRate(_ device: AudioObjectID) throws -> Float64 {
    var property = address(kAudioDevicePropertyNominalSampleRate)
    var value = Float64.zero
    var size = UInt32(MemoryLayout<Float64>.size)
    try check(AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value),
              "Read output sample rate")
    guard value.isFinite && value > 0 else {
        throw NSError(domain: "SystemAudioMonitor", code: 3,
                      userInfo: [NSLocalizedDescriptionKey: "Invalid output sample rate"])
    }
    return value
}

func scalarProperty(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector) -> Float32? {
    var property = address(selector, kAudioDevicePropertyScopeOutput)
    guard AudioObjectHasProperty(device, &property) else { return nil }
    var value = Float32.zero
    var size = UInt32(MemoryLayout<Float32>.size)
    guard AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value) == noErr,
          value.isFinite else { return nil }
    return value
}

func booleanProperty(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector) -> Bool? {
    var property = address(selector, kAudioDevicePropertyScopeOutput)
    guard AudioObjectHasProperty(device, &property) else { return nil }
    var value: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    guard AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value) == noErr else { return nil }
    return value != 0
}

func volumeWritable(_ device: AudioObjectID) -> Bool {
    var property = address(kAudioDevicePropertyVolumeScalar, kAudioDevicePropertyScopeOutput)
    guard AudioObjectHasProperty(device, &property) else { return false }
    var value = DarwinBoolean(false)
    return AudioObjectIsPropertySettable(device, &property, &value) == noErr && value.boolValue
}

func decibels(_ amplitude: Double) -> Double {
    amplitude > 0 ? max(-120, 20 * log10(amplitude)) : -120
}

struct WindowMeter {
    var squares = 0.0
    var samples: UInt64 = 0
    var peak = 0.0
    var frames: UInt64 = 0
    var callbacks: UInt64 = 0
    var droppedFrames: UInt64 = 0
    var nextSample: Double?
    var maxCallbackSeconds = 0.0
    var maxCallbackIntervalSeconds = 0.0
    var lastCallback = ProcessInfo.processInfo.systemUptime
    var failure: String?

    mutating func consume(_ buffers: UnsafePointer<AudioBufferList>, stamp: UnsafePointer<AudioTimeStamp>,
                          bytesPerFrame: UInt32) {
        let started = ProcessInfo.processInfo.systemUptime
        if callbacks > 0 { maxCallbackIntervalSeconds = max(maxCallbackIntervalSeconds, started - lastCallback) }
        lastCallback = started
        callbacks += 1
        let list = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: buffers))
        var callbackFrames: UInt32 = 0
        for buffer in list {
            guard let data = buffer.mData else { continue }
            let count = Int(buffer.mDataByteSize) / MemoryLayout<Float32>.size
            if callbackFrames == 0 && bytesPerFrame > 0 {
                callbackFrames = buffer.mDataByteSize / bytesPerFrame
            }
            let values = data.assumingMemoryBound(to: Float32.self)
            for index in 0..<count {
                let value = Double(values[index])
                guard value.isFinite else { continue }
                squares += value * value
                peak = max(peak, abs(value))
                samples += 1
            }
        }
        frames += UInt64(callbackFrames)
        if stamp.pointee.mFlags.contains(.sampleTimeValid) {
            let position = stamp.pointee.mSampleTime
            if let expected = nextSample, position > expected + 1 {
                droppedFrames += UInt64(min(position - expected, Double(Int64.max)))
            }
            if let expected = nextSample, position < expected - 1 {
                failure = "Audio timestamp moved backwards"
            }
            nextSample = position + Double(callbackFrames)
        }
        maxCallbackSeconds = max(maxCallbackSeconds, ProcessInfo.processInfo.systemUptime - started)
    }

    mutating func take() -> [String: Any]? {
        guard samples > 0 else { return nil }
        let result: [String: Any] = [
            "rmsDbfs": decibels(sqrt(squares / Double(samples))),
            "peakDbfs": decibels(peak),
            "frames": frames,
            "callbacks": callbacks,
            "droppedFrames": droppedFrames,
            "maxCallbackSeconds": maxCallbackSeconds,
            "maxCallbackIntervalSeconds": maxCallbackIntervalSeconds
        ]
        squares = 0; samples = 0; peak = 0; frames = 0; callbacks = 0
        droppedFrames = 0; maxCallbackSeconds = 0; maxCallbackIntervalSeconds = 0
        return result
    }
}

@available(macOS 14.4, *)
func monitor() throws {
    let output = try defaultOutput()
    let deviceID = try stringProperty(output, kAudioDevicePropertyDeviceUID, "Read output UID")
    let deviceName = try stringProperty(output, kAudioObjectPropertyName, "Read output name")
    let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
    description.name = "System Audio Auto Volume read-only monitor"
    description.isPrivate = true
    description.muteBehavior = .unmuted
    var tap = AudioObjectID(0)
    try check(AudioHardwareCreateProcessTap(description, &tap),
              "Create audio tap (allow System Audio Recording in Privacy settings)")
    defer { AudioHardwareDestroyProcessTap(tap) }

    let composition: [String: Any] = [
        kAudioAggregateDeviceNameKey: "System Audio Auto Volume monitor",
        kAudioAggregateDeviceUIDKey: UUID().uuidString,
        kAudioAggregateDeviceIsPrivateKey: true,
        kAudioAggregateDeviceMainSubDeviceKey: deviceID,
        kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: deviceID]],
        kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: description.uuid.uuidString,
                                           kAudioSubTapDriftCompensationKey: true]],
        kAudioAggregateDeviceTapAutoStartKey: false
    ]
    var aggregate = AudioObjectID(0)
    try check(AudioHardwareCreateAggregateDevice(composition as CFDictionary, &aggregate),
              "Create private monitor device")
    defer { AudioHardwareDestroyAggregateDevice(aggregate) }

    var formatProperty = address(kAudioDevicePropertyStreamFormat,
                                 kAudioDevicePropertyScopeInput)
    var format = AudioStreamBasicDescription()
    var formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    try check(AudioObjectGetPropertyData(aggregate, &formatProperty, 0, nil, &formatSize, &format),
              "Read monitor input format")
    guard format.mFormatID == kAudioFormatLinearPCM,
          format.mBitsPerChannel == 32,
          format.mFormatFlags & kAudioFormatFlagIsFloat != 0 else {
        throw NSError(domain: "SystemAudioMonitor", code: 4,
                      userInfo: [NSLocalizedDescriptionKey: "Expected Float32 PCM tap format"])
    }
    let rate = try sampleRate(output)
    let queue = DispatchQueue(label: "system-audio.read-only-meter")
    var meter = WindowMeter()
    var stopped = false
    var io: AudioDeviceIOProcID?
    try check(AudioDeviceCreateIOProcIDWithBlock(&io, aggregate, queue) { _, input, stamp, _, _ in
        meter.consume(input, stamp: stamp, bytesPerFrame: format.mBytesPerFrame)
    }, "Create monitor callback")
    defer { if let io { AudioDeviceDestroyIOProcID(aggregate, io) } }
    try check(AudioDeviceStart(aggregate, io), "Start system audio monitor")
    defer { AudioDeviceStop(aggregate, io) }

    emit(["schemaVersion": schema, "event": "ready", "timestampMs": Date().timeIntervalSince1970 * 1000,
          "deviceId": deviceID, "deviceName": deviceName, "sampleRate": rate,
          "channels": format.mChannelsPerFrame,
          "systemVolume": scalarProperty(output, kAudioDevicePropertyVolumeScalar).map { Double($0) * 100 } as Any? ?? NSNull(),
          "volumeReadable": scalarProperty(output, kAudioDevicePropertyVolumeScalar) != nil,
          "volumeWritableCapability": volumeWritable(output),
          "muted": booleanProperty(output, kAudioDevicePropertyMute) as Any? ?? NSNull()])

    DispatchQueue.global().async {
        while let line = readLine() {
            if line.trimmingCharacters(in: .whitespacesAndNewlines) == "stop" { break }
        }
        queue.async { stopped = true }
    }

    while true {
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.25))
        if try defaultOutput() != output {
            emit(["schemaVersion": schema, "event": "device-changed",
                  "timestampMs": Date().timeIntervalSince1970 * 1000,
                  "deviceId": deviceID, "deviceName": deviceName])
            break
        }
        let snapshot = queue.sync { () -> ([String: Any]?, Bool, String?, Double) in
            (meter.take(), stopped, meter.failure, meter.lastCallback)
        }
        if snapshot.1 { break }
        if let failure = snapshot.2 {
            throw NSError(domain: "SystemAudioMonitor", code: 5,
                          userInfo: [NSLocalizedDescriptionKey: failure])
        }
        if ProcessInfo.processInfo.systemUptime - snapshot.3 > 2 {
            throw NSError(domain: "SystemAudioMonitor", code: 6,
                          userInfo: [NSLocalizedDescriptionKey: "Audio callbacks stopped; check permission and output device"])
        }
        guard var values = snapshot.0 else { continue }
        values.merge(["schemaVersion": schema, "event": "meter",
                      "timestampMs": Date().timeIntervalSince1970 * 1000,
                      "deviceId": deviceID, "deviceName": deviceName,
                      "sampleRate": rate, "channels": format.mChannelsPerFrame,
                      "systemVolume": scalarProperty(output, kAudioDevicePropertyVolumeScalar).map { Double($0) * 100 } as Any? ?? NSNull(),
                      "volumeReadable": scalarProperty(output, kAudioDevicePropertyVolumeScalar) != nil,
                      "volumeWritableCapability": volumeWritable(output),
                      "muted": booleanProperty(output, kAudioDevicePropertyMute) as Any? ?? NSNull()]) { _, new in new }
        emit(values)
    }
}

do {
    guard CommandLine.arguments.count == 1 else {
        throw NSError(domain: "SystemAudioMonitor", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "Usage: SystemAudioMonitor"])
    }
    if #available(macOS 14.4, *) { try monitor() }
    else {
        throw NSError(domain: "SystemAudioMonitor", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "Requires macOS 14.4 or newer"])
    }
} catch {
    emit(["schemaVersion": schema, "event": "error",
          "timestampMs": Date().timeIntervalSince1970 * 1000,
          "message": error.localizedDescription])
    exit(1)
}
