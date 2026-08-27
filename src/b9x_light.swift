// SPDX-License-Identifier: MIT
import CoreBluetooth
import Foundation

private let serviceUUID = CBUUID(string: "FFE0")
private let writeUUID = CBUUID(string: "FFE1")
private let notifyUUID = CBUUID(string: "FFE4")
private let applyPacket = Data([0x51, 0x0B])

private struct RequestedColor {
    let name: String
    let red: UInt8
    let green: UInt8
    let blue: UInt8
}

private let colors: [String: RequestedColor] = [
    "green": RequestedColor(name: "green", red: 0x00, green: 0xFF, blue: 0x00),
    "yellow": RequestedColor(name: "yellow", red: 0xFF, green: 0xFF, blue: 0x00),
    "red": RequestedColor(name: "red", red: 0xFF, green: 0x00, blue: 0x00),
]

private func configurationPacket(for color: RequestedColor) -> Data {
    var bytes = [UInt8](repeating: 0, count: 20)
    bytes[0] = 0x50
    bytes[1] = 0x0B
    bytes[2] = 0x00
    bytes[3] = 0x01
    bytes[4] = 0x01
    bytes[5] = color.red
    bytes[6] = color.green
    bytes[7] = color.blue
    bytes[17] = 0x14
    bytes[18] = 0x00
    bytes[19] = UInt8(bytes[0..<19].reduce(0) { ($0 + Int($1)) & 0xFF })
    return Data(bytes)
}

private func protocolSelfCheck() -> Bool {
    let expected: [String: String] = [
        "green": "50 0B 00 01 01 00 FF 00 00 00 00 00 00 00 00 00 00 14 00 70",
        "yellow": "50 0B 00 01 01 FF FF 00 00 00 00 00 00 00 00 00 00 14 00 6F",
        "red": "50 0B 00 01 01 FF 00 00 00 00 00 00 00 00 00 00 00 14 00 70",
    ]
    return colors.allSatisfy { name, color in
        configurationPacket(for: color).hex == expected[name]
    }
}

final class B9XLight: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private let command: String
    private let requestedColor: RequestedColor?
    private var central: CBCentralManager!
    private var target: CBPeripheral?
    private var writeCharacteristic: CBCharacteristic?
    private var timeout: Timer?
    private var writeStage = 0
    private var applyAcknowledged = false
    private var matchingResponse: Data?
    private var finished = false

    init(command: String) {
        self.command = command
        self.requestedColor = colors[command]
        super.init()
        central = CBCentralManager(delegate: self, queue: nil)
        timeout = Timer.scheduledTimer(withTimeInterval: command == "scan" ? 12 : 20,
                                       repeats: false) { _ in
            self.finish(code: 4, message: "ERROR B9X not found or operation timed out")
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            if central.state == .poweredOff {
                finish(code: 3, message: "ERROR Bluetooth is turned off")
            } else if central.state == .unauthorized {
                finish(code: 3, message: "ERROR Bluetooth permission denied")
            } else if central.state == .unsupported {
                finish(code: 3, message: "ERROR Bluetooth unsupported")
            }
            return
        }
        central.scanForPeripherals(withServices: [serviceUUID], options: nil)
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let name = advertisedName ?? peripheral.name ?? "<unnamed>"
        guard name == "Flydigi B9X", target == nil else { return }

        if command == "scan" {
            finish(code: 0, message: "SCAN_RESULT device=Flydigi_B9X uuid=\(peripheral.identifier.uuidString) rssi=\(RSSI) service=FFE0")
            return
        }

        target = peripheral
        peripheral.delegate = self
        central.stopScan()
        central.connect(peripheral, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral,
                        error: Error?) {
        finish(code: 5, message: "ERROR B9X connection failed: \(String(describing: error))")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral,
                        error: Error?) {
        if !finished {
            finish(code: 6, message: "ERROR B9X connection dropped: \(String(describing: error))")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            finish(code: 7, message: "ERROR GATT service discovery failed: \(error)")
            return
        }
        guard let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            finish(code: 7, message: "ERROR B9X service FFE0 not found")
            return
        }
        peripheral.discoverCharacteristics([writeUUID, notifyUUID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        if let error {
            finish(code: 8, message: "ERROR GATT characteristic discovery failed: \(error)")
            return
        }
        var notifyCharacteristic: CBCharacteristic?
        for characteristic in service.characteristics ?? [] {
            if characteristic.uuid == writeUUID { writeCharacteristic = characteristic }
            if characteristic.uuid == notifyUUID { notifyCharacteristic = characteristic }
        }
        guard let writeCharacteristic, writeCharacteristic.properties.contains(.write),
              let notifyCharacteristic, notifyCharacteristic.properties.contains(.notify) else {
            finish(code: 8, message: "ERROR required FFE1 write / FFE4 notify characteristics unavailable")
            return
        }

        if command == "status" {
            finish(code: 0, message: "STATUS device=Flydigi_B9X bluetooth=on connected=true service=FFE0 write=FFE1 notify=FFE4")
            return
        }

        peripheral.setNotifyValue(true, for: notifyCharacteristic)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic,
                    error: Error?) {
        if let error {
            finish(code: 9, message: "ERROR FFE4 notification subscription failed: \(error)")
            return
        }
        guard characteristic.uuid == notifyUUID, characteristic.isNotifying,
              let requestedColor, let writeCharacteristic else { return }

        let packet = configurationPacket(for: requestedColor)
        writeStage = 1
        print("WRITE color=\(requestedColor.name) packet=1 payload=\(packet.hex)")
        peripheral.writeValue(packet, for: writeCharacteristic, type: .withResponse)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        if let error {
            finish(code: 10, message: "ERROR FFE1 write failed: \(error)")
            return
        }
        guard let writeCharacteristic else {
            finish(code: 10, message: "ERROR FFE1 characteristic lost")
            return
        }
        if writeStage == 1 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                self.writeStage = 2
                print("WRITE color=\(self.command) packet=2 payload=\(applyPacket.hex)")
                peripheral.writeValue(applyPacket, for: writeCharacteristic, type: .withResponse)
            }
        } else if writeStage == 2 {
            applyAcknowledged = true
            completeColorIfReady()
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        if let error {
            finish(code: 11, message: "ERROR FFE4 notification failed: \(error)")
            return
        }
        guard characteristic.uuid == notifyUUID, let value = characteristic.value,
              let requestedColor else { return }
        print("NOTIFY payload=\(value.hex)")
        guard value.count >= 20,
              value[0] == 0x51, value[1] == 0x0B,
              value[3] == 0x01, value[4] == 0x01,
              value[5] == requestedColor.red,
              value[6] == requestedColor.green,
              value[7] == requestedColor.blue,
              value[17] == 0x14 else { return }
        matchingResponse = value
        completeColorIfReady()
    }

    private func completeColorIfReady() {
        guard applyAcknowledged, let matchingResponse, let requestedColor else { return }
        finish(code: 0, message: "COLOR_SET color=\(requestedColor.name) rgb=\(requestedColor.red),\(requestedColor.green),\(requestedColor.blue) device_response=\(matchingResponse.hex)")
    }

    private func finish(code: Int32, message: String) {
        guard !finished else { return }
        finished = true
        timeout?.invalidate()
        central.stopScan()
        if let target { central.cancelPeripheralConnection(target) }
        let stream = code == 0 ? stdout : stderr
        fputs(message + "\n", stream)
        fflush(stream)
        exit(code)
    }
}

extension Data {
    var hex: String { map { String(format: "%02X", $0) }.joined(separator: " ") }
}

guard protocolSelfCheck() else {
    fputs("ERROR internal protocol self-check failed\n", stderr)
    exit(70)
}

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: b9x-light scan|status|green|yellow|red\n", stderr)
    exit(2)
}

let command = CommandLine.arguments[1].lowercased()
guard command == "scan" || command == "status" || colors[command] != nil else {
    fputs("ERROR unsupported command: \(CommandLine.arguments[1])\n", stderr)
    fputs("Usage: b9x-light scan|status|green|yellow|red\n", stderr)
    exit(2)
}

let runner = B9XLight(command: command)
RunLoop.main.run()
