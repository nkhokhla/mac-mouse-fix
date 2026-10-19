import Foundation
import CryptoKit

// Verify with the public key shipped in the app; never accept a key from the feed.
guard CommandLine.arguments.count == 4,
      let key = Data(base64Encoded: CommandLine.arguments[1]),
      let signature = Data(base64Encoded: CommandLine.arguments[2]) else { exit(2) }
let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[3]))
let publicKey = try Curve25519.Signing.PublicKey(rawRepresentation: key)
guard publicKey.isValidSignature(signature, for: data) else {
    fputs("Invalid update signature\n", stderr)
    exit(1)
}
print("Update signature verified")
