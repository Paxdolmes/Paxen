// Used by the iPhone build (.github/workflows/ios-testflight.yml) only, after `npm ci`.
//
// expo-modules-jsi 58.0.21 doesn't compile with Xcode 26.3 (GitHub's Intel Mac, the only hosted Mac available while
// the Apple-silicon ones are short): one closure captures a `nonisolated(unsafe) let` pointer, which that compiler
// rejects with "sending 'slot' risks causing data races" (newer Xcodes accept it). Expo's own UncheckedSendable
// helper exists for exactly this case ("use it instead of a nonisolated(unsafe) let local captured by such a
// closure"), so the capture goes through it, as Expo does elsewhere. Same pointer, same behaviour.
//
// It only changes the file if the original text is there: once Expo fixes it, this does nothing.
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const root = dirname(require.resolve("expo-modules-jsi/package.json"));
const file = join(root, "apple/Sources/ExpoModulesJSI/Runtime/Values/JavaScriptObject.swift");

const before = `    try runtime._withUnsafeGuaranteedRef { runtime in
      try JavaScriptActor.assumeIsolated {
        try encode(JavaScriptValue.Slot(slot), runtime)
      }
    }`;
const after = `    let sendableSlot = UncheckedSendable(slot)
    try runtime._withUnsafeGuaranteedRef { runtime in
      try JavaScriptActor.assumeIsolated {
        try encode(JavaScriptValue.Slot(sendableSlot.value), runtime)
      }
    }`;

const source = readFileSync(file, "utf8");
if (source.includes(after)) {
  console.log("expo-modules-jsi: already patched");
} else if (source.split(before).length === 2) {
  writeFileSync(file, source.replace(before, after));
  console.log("expo-modules-jsi: patched the slot capture in JavaScriptObject.swift for Xcode 26.3");
} else {
  console.log("expo-modules-jsi: original text not found (fixed upstream?), nothing changed");
}
