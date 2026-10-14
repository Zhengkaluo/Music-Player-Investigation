// macOS 14.4+ system-output meter with explicit M6 manual volume calibration commands.
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

func uint32Property(_ device: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32? {
    var property = address(selector)
    guard AudioObjectHasProperty(device, &property) else { return nil }
    var value: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    guard AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value) == noErr else {
        return nil
    }
    return value
}

func deviceTransport(_ device: AudioObjectID) -> String {
    guard let value = uint32Property(device, kAudioDevicePropertyTransportType) else {
        return "unknown"
    }
    switch value {
    case kAudioDeviceTransportTypeBuiltIn: return "built-in"
    case kAudioDeviceTransportTypeBluetooth, kAudioDeviceTransportTypeBluetoothLE: return "bluetooth"
    case kAudioDeviceTransportTypeHDMI, kAudioDeviceTransportTypeDisplayPort: return "display"
    case kAudioDeviceTransportTypeUSB: return "usb"
    case kAudioDeviceTransportTypeAirPlay: return "airplay"
    default: return "other"
    }
}

func volumeRange(_ device: AudioObjectID) -> AudioValueRange? {
    var property = address(kAudioDevicePropertyVolumeRangeDecibels,
                           kAudioDevicePropertyScopeOutput)
    guard AudioObjectHasProperty(device, &property) else { return nil }
    var value = AudioValueRange()
    var size = UInt32(MemoryLayout<AudioValueRange>.size)
    guard AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value) == noErr,
          value.mMinimum.isFinite, value.mMaximum.isFinite,
          value.mMinimum < value.mMaximum else { return nil }
    return value
}

func scalarToDecibels(_ device: AudioObjectID, _ scalar: Float32) -> Float32? {
    var property = address(kAudioDevicePropertyVolumeScalarToDecibels,
                           kAudioDevicePropertyScopeOutput)
    guard AudioObjectHasProperty(device, &property) else { return nil }
    var value = scalar
    var size = UInt32(MemoryLayout<Float32>.size)
    guard AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value) == noErr,
          value.isFinite else { return nil }
    return value
}

func decibelsToScalar(_ device: AudioObjectID, _ decibels: Float32) -> Float32? {
    var property = address(kAudioDevicePropertyVolumeDecibelsToScalar,
                           kAudioDevicePropertyScopeOutput)
    guard AudioObjectHasProperty(device, &property) else { return nil }
    var value = decibels
    var size = UInt32(MemoryLayout<Float32>.size)
    guard AudioObjectGetPropertyData(device, &property, 0, nil, &size, &value) == noErr,
          value.isFinite, (0...1).contains(value) else { return nil }
    return value
}

func volumeDbCapability(_ device: AudioObjectID) -> [String: Any] {
    let scalar = scalarProperty(device, kAudioDevicePropertyVolumeScalar)
    let direct = scalarProperty(device, kAudioDevicePropertyVolumeDecibels)
    let converted = scalar.flatMap { scalarToDecibels(device, $0) }
    let current = direct ?? converted
    let range = volumeRange(device)
    let reliable = current != nil && range != nil
    let source: Any
    if direct != nil {
        source = "coreaudio-volume-decibels"
    } else if converted != nil {
        source = "coreaudio-scalar-to-decibels"
    } else {
        source = NSNull()
    }
    let attenuation = (current != nil && range != nil)
        ? Double(current!) - range!.mMaximum : nil
    return [
        "systemVolumeDb": current.map { Double($0) } as Any? ?? NSNull(),
        "volumeDbMin": range.map { $0.mMinimum } as Any? ?? NSNull(),
        "volumeDbMax": range.map { $0.mMaximum } as Any? ?? NSNull(),
        "volumeDbStep": NSNull(),
        "outputAttenuationDb": attenuation as Any? ?? NSNull(),
        "volumeDbSource": source,
        "volumeDbMappingReliable": reliable,
        "deviceTransport": deviceTransport(device),
    ]
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

func setVolume(_ device: AudioObjectID, percent: Double) throws -> Double {
    guard percent.isFinite && (0...100).contains(percent) else {
        throw NSError(domain: "SystemAudioMonitor", code: 9,
                      userInfo: [NSLocalizedDescriptionKey: "Volume must be 0...100"])
    }
    var property = address(kAudioDevicePropertyVolumeScalar, kAudioDevicePropertyScopeOutput)
    guard volumeWritable(device) else {
        throw NSError(domain: "SystemAudioMonitor", code: 10,
                      userInfo: [NSLocalizedDescriptionKey: "Default output volume is not writable"])
    }
    var value = Float32(percent / 100)
    let size = UInt32(MemoryLayout<Float32>.size)
    try check(AudioObjectSetPropertyData(device, &property, 0, nil, size, &value),
              "Write output volume")
    Thread.sleep(forTimeInterval: 0.05)
    guard let actual = scalarProperty(device, kAudioDevicePropertyVolumeScalar) else {
        throw NSError(domain: "SystemAudioMonitor", code: 11,
                      userInfo: [NSLocalizedDescriptionKey: "Cannot verify output volume"])
    }
    return Double(actual) * 100
}

func volumeState(_ event: String) throws -> [String: Any] {
    let device = try defaultOutput()
    let deviceID = try stringProperty(device, kAudioDevicePropertyDeviceUID, "Read output UID")
    let deviceName = try stringProperty(device, kAudioObjectPropertyName, "Read output name")
    var result: [String: Any] = [
        "schemaVersion": schema, "event": event,
        "timestampMs": Date().timeIntervalSince1970 * 1000,
        "deviceId": deviceID, "deviceName": deviceName,
        "systemVolume": scalarProperty(device, kAudioDevicePropertyVolumeScalar).map { Double($0) * 100 } as Any? ?? NSNull(),
        "volumeReadable": scalarProperty(device, kAudioDevicePropertyVolumeScalar) != nil,
        "volumeWritableCapability": volumeWritable(device),
        "muted": booleanProperty(device, kAudioDevicePropertyMute) as Any? ?? NSNull(),
    ]
    result.merge(volumeDbCapability(device)) { _, new in new }
    return result
}

func convertVolumeTarget(_ targetDb: Double) throws -> [String: Any] {
    let device = try defaultOutput()
    let deviceID = try stringProperty(device, kAudioDevicePropertyDeviceUID, "Read output UID")
    guard let range = volumeRange(device), targetDb.isFinite,
          targetDb >= range.mMinimum, targetDb <= range.mMaximum,
          let scalar = decibelsToScalar(device, Float32(targetDb)) else {
        throw NSError(domain: "SystemAudioMonitor", code: 17,
                      userInfo: [NSLocalizedDescriptionKey: "Cannot convert target dB to scalar"])
    }
    return ["schemaVersion": schema, "event": "volume-target-converted",
            "timestampMs": Date().timeIntervalSince1970 * 1000,
            "deviceId": deviceID, "targetDb": targetDb,
            "targetVolume": Double(scalar) * 100]
}

func lowerVolumeForTest(step: Double) throws -> [String: Any] {
    guard step.isFinite && (0.1...3).contains(step) else {
        throw NSError(domain: "SystemAudioMonitor", code: 12,
                      userInfo: [NSLocalizedDescriptionKey: "Test step must be 0.1...3 percentage points"])
    }
    let device = try defaultOutput()
    let deviceID = try stringProperty(device, kAudioDevicePropertyDeviceUID, "Read output UID")
    let deviceName = try stringProperty(device, kAudioObjectPropertyName, "Read output name")
    guard let scalar = scalarProperty(device, kAudioDevicePropertyVolumeScalar) else {
        throw NSError(domain: "SystemAudioMonitor", code: 13,
                      userInfo: [NSLocalizedDescriptionKey: "Default output volume is not readable"])
    }
    let baseline = Double(scalar) * 100
    let actual = try setVolume(device, percent: max(0, baseline - step))
    return ["schemaVersion": schema, "event": "volume-test-lowered",
            "timestampMs": Date().timeIntervalSince1970 * 1000,
            "deviceId": deviceID, "deviceName": deviceName,
            "beforeVolume": baseline, "appliedVolume": actual,
            "muted": booleanProperty(device, kAudioDevicePropertyMute) as Any? ?? NSNull()]
}

func restoreVolumeAfterTest(baseline: Double, written: Double, deviceID: String) throws -> [String: Any] {
    let device = try defaultOutput()
    let currentID = try stringProperty(device, kAudioDevicePropertyDeviceUID, "Read output UID")
    guard currentID == deviceID else {
        throw NSError(domain: "SystemAudioMonitor", code: 14,
                      userInfo: [NSLocalizedDescriptionKey: "Output device changed; refusing restore"])
    }
    guard let scalar = scalarProperty(device, kAudioDevicePropertyVolumeScalar) else {
        throw NSError(domain: "SystemAudioMonitor", code: 15,
                      userInfo: [NSLocalizedDescriptionKey: "Default output volume is not readable"])
    }
    let current = Double(scalar) * 100
    guard abs(current - written) <= 0.6 else {
        throw NSError(domain: "SystemAudioMonitor", code: 16,
                      userInfo: [NSLocalizedDescriptionKey: "Volume changed after test; refusing restore"])
    }
    let actual = try setVolume(device, percent: baseline)
    return ["schemaVersion": schema, "event": "volume-test-restored",
            "timestampMs": Date().timeIntervalSince1970 * 1000,
            "deviceId": currentID, "beforeVolume": current, "appliedVolume": actual]
}

func decibels(_ amplitude: Double) -> Double {
    amplitude > 0 ? max(-120, 20 * log10(amplitude)) : -120
}

func kWeightingCoefficients(_ sampleRate: Double) -> [[Double]] {
    let shelfFrequency = 1681.974450955533
    let shelfGain = 3.999843853973347
    let shelfQuality = 0.7071752369554196
    var k = tan(.pi * shelfFrequency / sampleRate)
    let vh = pow(10, shelfGain / 20)
    let vb = pow(vh, 0.4996667741545416)
    var denominator = 1 + k / shelfQuality + k * k
    let shelf = [
        (vh + vb * k / shelfQuality + k * k) / denominator,
        2 * (k * k - vh) / denominator,
        (vh - vb * k / shelfQuality + k * k) / denominator,
        2 * (k * k - 1) / denominator,
        (1 - k / shelfQuality + k * k) / denominator
    ]
    let highPassFrequency = 38.13547087602444
    let highPassQuality = 0.5003270373238773
    k = tan(.pi * highPassFrequency / sampleRate)
    denominator = 1 + k / highPassQuality + k * k
    let highPass = [1, -2, 1,
                    2 * (k * k - 1) / denominator,
                    (1 - k / highPassQuality + k * k) / denominator]
    return [shelf, highPass]
}

struct Biquad {
    let b0: Double, b1: Double, b2: Double, a1: Double, a2: Double
    var z1 = 0.0, z2 = 0.0

    init(_ values: [Double]) {
        b0 = values[0]; b1 = values[1]; b2 = values[2]
        a1 = values[3]; a2 = values[4]
    }

    mutating func process(_ value: Double) -> Double {
        let result = b0 * value + z1
        z1 = b1 * value - a1 * result + z2
        z2 = b2 * value - a2 * result
        return result
    }
}

struct LoudnessMeter {
    var filters: [[Biquad]]
    let blockFrames: Int
    var blockEnergy = 0.0
    var blockCount = 0
    var blocks: [Double] = []

    init(sampleRate: Double, channels: Int) {
        let coefficients = kWeightingCoefficients(sampleRate)
        filters = (0..<channels).map { _ in coefficients.map(Biquad.init) }
        blockFrames = Int((sampleRate / 10).rounded())
    }

    mutating func consume(_ sample: Double, channel: Int) {
        var value = sample.isFinite ? sample : 0
        for index in filters[channel].indices {
            value = filters[channel][index].process(value)
        }
        blockEnergy += value * value
        if channel == filters.count - 1 {
            blockCount += 1
            if blockCount == blockFrames {
                blocks.append(blockEnergy / Double(blockFrames))
                if blocks.count > 30 { blocks.removeFirst() }
                blockEnergy = 0
                blockCount = 0
            }
        }
    }

    func lufs(_ values: ArraySlice<Double>) -> Double {
        let energy = values.reduce(0, +) / Double(values.count)
        return energy > 0 ? max(-120, -0.691 + 10 * log10(energy)) : -120
    }

    func snapshot() -> (Double?, Double?) {
        let momentary = blocks.count >= 4 ? lufs(blocks.suffix(4)) : nil
        let shortTerm = blocks.count >= 30 ? lufs(blocks.suffix(30)) : nil
        return (momentary, shortTerm)
    }
}

enum PeakGuardState: String {
    case armed = "ARMED", attack = "ATTACK", hold = "HOLD", release = "RELEASE"
}

struct PeakGuard {
    let channelCount: Int
    let blockFrames: Int
    let warmupBlocks = 100, minBlocks = 2, holdBlocks = 50, releaseBlocks = 200, cooldownBlocks = 100
    let peakThresholdDbfs = -1.0, relativeJumpThresholdDb = 10.0, maxAttenuationDb = 12.0
    let baselineAlpha = 1 - exp(-0.01)
    var baselineEnergy = pow(10.0, -6.0)
    var frameEnergy = 0.0, framePeak = 0.0
    var blockEnergy = 0.0, blockPeak = 0.0
    var frameCount = 0, candidateBlocks = 0, blockIndex = 0
    var holdRemaining = 0, releaseRemaining = 0, cooldownRemaining = 0
    var state = PeakGuardState.armed
    var attenuationDb = 0.0, attackAttenuationDb = 0.0
    var triggerCount = 0
    var samplePeakDbfs: Double?, fastRmsDbfs: Double?, baselineRmsDbfs: Double?, relativeJumpDb: Double?
    var lastTriggerBlock: Int?
    var lastTriggerSamplePeak = 0.0, lastTriggerFastRms = 0.0
    var lastTriggerBaseline = 0.0, lastTriggerJump = 0.0, lastTriggerAttenuation = 0.0

    init(sampleRate: Double, channels: Int) {
        channelCount = channels
        blockFrames = Int((sampleRate / 100).rounded())
    }

    mutating func consume(_ value: Double, channel: Int) {
        let sample = value.isFinite ? value : 0
        frameEnergy += sample * sample
        framePeak = max(framePeak, abs(sample))
        guard channel == channelCount - 1 else { return }
        blockEnergy += frameEnergy / Double(channelCount)
        blockPeak = max(blockPeak, framePeak)
        frameEnergy = 0; framePeak = 0; frameCount += 1
        if frameCount == blockFrames { finishBlock() }
    }

    mutating func finishBlock() {
        let energy = blockEnergy / Double(blockFrames)
        fastRmsDbfs = decibels(sqrt(energy))
        baselineRmsDbfs = decibels(sqrt(baselineEnergy))
        samplePeakDbfs = decibels(blockPeak)
        relativeJumpDb = max(0, fastRmsDbfs! - baselineRmsDbfs!)
        blockIndex += 1
        let condition = blockIndex >= warmupBlocks && samplePeakDbfs! >= peakThresholdDbfs &&
                        relativeJumpDb! >= relativeJumpThresholdDb

        switch state {
        case .armed:
            if cooldownRemaining > 0 {
                cooldownRemaining -= 1
                candidateBlocks = 0
            } else if condition {
                candidateBlocks += 1
                if candidateBlocks >= minBlocks {
                    attackAttenuationDb = -min(maxAttenuationDb, relativeJumpDb!)
                    attenuationDb = attackAttenuationDb
                    state = .attack
                    triggerCount += 1
                    lastTriggerBlock = blockIndex
                    lastTriggerSamplePeak = samplePeakDbfs!
                    lastTriggerFastRms = fastRmsDbfs!
                    lastTriggerBaseline = baselineRmsDbfs!
                    lastTriggerJump = relativeJumpDb!
                    lastTriggerAttenuation = attenuationDb
                    candidateBlocks = 0
                }
            } else {
                candidateBlocks = 0
                baselineEnergy += baselineAlpha * (energy - baselineEnergy)
            }
        case .attack:
            state = .hold
            holdRemaining = holdBlocks
        case .hold:
            holdRemaining -= 1
            if holdRemaining <= 0 {
                state = .release
                releaseRemaining = releaseBlocks
            }
        case .release:
            releaseRemaining -= 1
            attenuationDb = attackAttenuationDb * Double(max(0, releaseRemaining)) /
                            Double(releaseBlocks)
            if releaseRemaining <= 0 {
                state = .armed
                attenuationDb = 0
                cooldownRemaining = cooldownBlocks
            }
        }
        blockEnergy = 0; blockPeak = 0; frameCount = 0
    }

    func snapshot() -> [String: Any] {
        let trigger: Any
        if let block = lastTriggerBlock {
            trigger = ["blockIndex": block,
                       "samplePeakDbfs": lastTriggerSamplePeak,
                       "fastRmsDbfs": lastTriggerFastRms,
                       "baselineRmsDbfs": lastTriggerBaseline,
                       "relativeJumpDb": lastTriggerJump,
                       "suggestedAttenuationDb": lastTriggerAttenuation] as [String: Any]
        } else {
            trigger = NSNull()
        }
        return ["mode": "shadow", "state": state.rawValue,
                "warmedUp": blockIndex >= warmupBlocks,
                "samplePeakDbfs": samplePeakDbfs as Any? ?? NSNull(),
                "truePeakDbtp": NSNull(),
                "fastRmsDbfs": fastRmsDbfs as Any? ?? NSNull(),
                "baselineRmsDbfs": baselineRmsDbfs as Any? ?? NSNull(),
                "relativeJumpDb": relativeJumpDb as Any? ?? NSNull(),
                "suggestedAttenuationDb": attenuationDb,
                "triggerCount": triggerCount, "lastTrigger": trigger,
                "execute": false]
    }
}

struct WindowMeter {
    let channelCount: Int
    let nonInterleaved: Bool
    var loudness: LoudnessMeter
    var peakGuard: PeakGuard
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

    init(sampleRate: Double, channels: Int, nonInterleaved: Bool) {
        channelCount = channels
        self.nonInterleaved = nonInterleaved
        loudness = LoudnessMeter(sampleRate: sampleRate, channels: channels)
        peakGuard = PeakGuard(sampleRate: sampleRate, channels: channels)
    }

    mutating func add(_ value: Double, channel: Int) {
        let sample = value.isFinite ? value : 0
        squares += sample * sample
        peak = max(peak, abs(sample))
        samples += 1
        loudness.consume(sample, channel: channel)
        peakGuard.consume(sample, channel: channel)
    }

    mutating func consume(_ buffers: UnsafePointer<AudioBufferList>, stamp: UnsafePointer<AudioTimeStamp>) {
        let started = ProcessInfo.processInfo.systemUptime
        if callbacks > 0 { maxCallbackIntervalSeconds = max(maxCallbackIntervalSeconds, started - lastCallback) }
        lastCallback = started
        callbacks += 1
        let list = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: buffers))
        var callbackFrames = 0
        if nonInterleaved {
            guard list.count >= channelCount else {
                failure = "Core Audio channel buffer count mismatch"
                return
            }
            callbackFrames = (0..<channelCount).compactMap { channel in
                list[channel].mData.map { _ in
                    Int(list[channel].mDataByteSize) / MemoryLayout<Float32>.size
                }
            }.min() ?? 0
            for frame in 0..<callbackFrames {
                for channel in 0..<channelCount {
                    guard let data = list[channel].mData else { continue }
                    add(Double(data.assumingMemoryBound(to: Float32.self)[frame]), channel: channel)
                }
            }
        } else if let buffer = list.first, let data = buffer.mData {
            let count = Int(buffer.mDataByteSize) / MemoryLayout<Float32>.size
            callbackFrames = count / channelCount
            let values = data.assumingMemoryBound(to: Float32.self)
            for index in 0..<(callbackFrames * channelCount) {
                add(Double(values[index]), channel: index % channelCount)
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
        let levels = loudness.snapshot()
        let result: [String: Any] = [
            "rmsDbfs": decibels(sqrt(squares / Double(samples))),
            "peakDbfs": decibels(peak),
            "momentaryLufs": levels.0 as Any? ?? NSNull(),
            "shortTermLufs": levels.1 as Any? ?? NSNull(),
            "peakGuard": peakGuard.snapshot(),
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

func loudnessSelfTest() {
    let rate = 48000.0
    var meter = LoudnessMeter(sampleRate: rate, channels: 2)
    var guardMeter = PeakGuard(sampleRate: rate, channels: 2)
    for frame in 0..<Int(rate * 4) {
        let sample = sin(2 * .pi * 1000 * Double(frame) / rate) * 0.125
        meter.consume(sample, channel: 0)
        meter.consume(sample, channel: 1)
    }
    for frame in 0..<Int(rate) {
        let sample = sin(2 * .pi * 1000 * Double(frame) / rate) * 0.05
        guardMeter.consume(sample, channel: 0)
        guardMeter.consume(sample, channel: 1)
    }
    for frame in 0..<Int(rate * 0.03) {
        let sample = sin(2 * .pi * 1000 * Double(frame) / rate)
        guardMeter.consume(sample, channel: 0)
        guardMeter.consume(sample, channel: 1)
    }
    let result = meter.snapshot()
    emit(["schemaVersion": schema, "event": "self-test",
          "momentaryLufs": result.0 as Any? ?? NSNull(),
          "shortTermLufs": result.1 as Any? ?? NSNull(),
          "peakGuard": guardMeter.snapshot()])
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
    guard format.mChannelsPerFrame == 2 else {
        throw NSError(domain: "SystemAudioMonitor", code: 8,
                      userInfo: [NSLocalizedDescriptionKey: "Expected stereo tap channels"])
    }
    let nonInterleaved = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
    var meter = WindowMeter(sampleRate: rate, channels: Int(format.mChannelsPerFrame),
                            nonInterleaved: nonInterleaved)
    var stopped = false
    var io: AudioDeviceIOProcID?
    try check(AudioDeviceCreateIOProcIDWithBlock(&io, aggregate, queue) { _, input, stamp, _, _ in
        meter.consume(input, stamp: stamp)
    }, "Create monitor callback")
    defer { if let io { AudioDeviceDestroyIOProcID(aggregate, io) } }
    try check(AudioDeviceStart(aggregate, io), "Start system audio monitor")
    defer { AudioDeviceStop(aggregate, io) }

    var ready: [String: Any] = ["schemaVersion": schema, "event": "ready", "timestampMs": Date().timeIntervalSince1970 * 1000,
          "deviceId": deviceID, "deviceName": deviceName, "sampleRate": rate,
          "channels": format.mChannelsPerFrame,
          "systemVolume": scalarProperty(output, kAudioDevicePropertyVolumeScalar).map { Double($0) * 100 } as Any? ?? NSNull(),
          "volumeReadable": scalarProperty(output, kAudioDevicePropertyVolumeScalar) != nil,
          "volumeWritableCapability": volumeWritable(output),
          "muted": booleanProperty(output, kAudioDevicePropertyMute) as Any? ?? NSNull()]
    ready.merge(volumeDbCapability(output)) { _, new in new }
    emit(ready)

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
        values.merge(volumeDbCapability(output)) { _, new in new }
        emit(values)
    }
}

do {
    if CommandLine.arguments == [CommandLine.arguments[0], "--self-test"] {
        loudnessSelfTest()
        exit(0)
    }
    if CommandLine.arguments == [CommandLine.arguments[0], "--volume-state"] {
        emit(try volumeState("volume-state"))
        exit(0)
    }
    if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--volume-convert-db",
       let target = Double(CommandLine.arguments[2]) {
        emit(try convertVolumeTarget(target))
        exit(0)
    }
    if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--volume-lower",
       let step = Double(CommandLine.arguments[2]) {
        emit(try lowerVolumeForTest(step: step))
        exit(0)
    }
    if CommandLine.arguments.count == 6 && CommandLine.arguments[1] == "--volume-restore",
       let baseline = Double(CommandLine.arguments[2]),
       let written = Double(CommandLine.arguments[3]),
       CommandLine.arguments[4] == "--device" {
        emit(try restoreVolumeAfterTest(baseline: baseline, written: written,
                                        deviceID: CommandLine.arguments[5]))
        exit(0)
    }
    guard CommandLine.arguments.count == 1 else {
        throw NSError(domain: "SystemAudioMonitor", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "Unknown command"])
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
