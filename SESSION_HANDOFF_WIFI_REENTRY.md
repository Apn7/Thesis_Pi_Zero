# Session handoff — Pi WiFi auto-join: on-device validation + re-entry fix

> **Date:** 2026-07-04 · **Device tested:** Realme GT Master Edition, Android 13
> (SDK 33), ColorOS / Realme UI.
> **Read `STEP2_PROVISIONING_HANDOFF.md` first** for the provisioning design.
> This doc records what we proved on real hardware, a nasty ColorOS gotcha +
> its recovery, and the **re-entry bug — now fixed in code** (needs one
> on-device confirmation run).

---

## 1. Confirmed working on hardware ✅ (do NOT regress this)

The full provisioning path is validated end-to-end on the Realme (Android 13):

- App launches → fires the `WifiNetworkSpecifier` request → the OS shows its
  network-request consent. On this ColorOS build the consent is an **intent
  chooser with two icons: "Settings" and "Wireless Settings".**
  - ✅ **"Settings"** (stock `com.android.settings/.wifi.NetworkRequestDialogActivity`)
    → shows **SmartCane-Cam → Connect**, works perfectly.
  - ❌ **"Wireless Settings"** (Oppo `com.oplus.wirelesssettings/...NetworkRequestDialogActivity`)
    → just dumps you into the WiFi list; **broken for our purpose.**
- After tapping **Connect** on the stock dialog: the phone joins SmartCane-Cam
  **fast**, and — the key success signal — shows *"switched to mobile data for
  continuous connection"*. Internet (Groq/LLM, geocoding) keeps working over
  cellular while the cane link carries frames + sonar. This is the app-scoped,
  local-only `WifiNetworkSpecifier` behaving exactly as designed.
- Replacing an already-connected **home WiFi** with the cane AP is **fast and
  automatic once the dialog is approved** — no aggressiveness tuning needed.

First connect within a session is solid. The re-entry drop (below) is **fixed**.

---

## 2. Re-entry drop — FIXED this session (code) ✅ · one device check left

**Symptom (was):** connect worked on first entry; **closing/backgrounding the
app and re-opening it dropped the cane WiFi and it did not re-join** — bad UX
for a blind user (link should stay up with the phone pocketed).

### Root cause (traced)

The cane WiFi request was **bound to the Activity, and actively torn down on
Activity destroy** — which *undermined the foreground service*:

- `CaneForegroundService` keeps the process alive across screen-off precisely so
  the TCP servers/inference/alerts keep running pocketed. **But**
  `MainActivity.onDestroy()` called `releasePiNetwork()` → `unregisterNetworkCallback`,
  and a `WifiNetworkSpecifier` network only lives while its callback is
  registered. So every time ColorOS destroyed the Activity (screen-off,
  backgrounding, re-entry) **the WiFi link dropped even though the service was
  keeping everything else alive.**
- `HomeScreen.dispose()` also called `PiWifiService.release()` (same teardown),
  and its `async` `release()` racing a re-entry `enableAutoJoin()` could leave
  Dart showing "connected" over a dead link.
- The callback lived on the (destroyed) Activity instance, so a re-created
  Activity saw `piWifiCallback == null` and could register a **second** request.

### The fix (implemented + compiles)

Made the WiFi request **process-scoped, idempotent, and not torn down on screen
teardown** — so it now truly rides the foreground service's process lifetime.

- **`MainActivity.kt`**
  - `piWifiChannel` / `piWifiCallback` / a new `piWifiConnected` flag / a
    `piWifiMainHandler` moved into the **`companion object` (process scope)**;
    the request is registered on **`applicationContext`**, not the Activity.
  - `requestPiNetwork()` is now **idempotent**: if a request is already
    registered it does **not** register a second — it re-emits the current state
    (`onPiWifiAvailable` if connected) so a **re-attached Dart engine re-syncs
    with no second consent prompt**.
  - `NetworkCallback` posts via `piWifiMainHandler` and maintains `piWifiConnected`.
  - **Removed `onDestroy()`'s `releasePiNetwork()`.** Added
    `cleanUpFlutterEngine()` that only **nulls the dead channel reference** (so
    the callback stops pushing into a detached engine) and **leaves the network
    registered.**
- **`home_screen.dart`** `dispose()` — **removed `PiWifiService.release()`**
  (kept `removeListener` + `disableAutoJoin`). The link is no longer dropped on
  screen teardown.
- **`pi_wifi_service.dart`** — doc + `onPiWifiLost` comment updated to describe
  the process-scoped, re-sync behaviour. (`release()` still exists as API but is
  no longer called on teardown; it drops the link only on a true session end.)

**Net effect:** screen-off / Activity re-create / re-entry keep the cane link up
(the service holds the process; the OS request rides it); returning to the app
re-syncs to the live link instead of re-joining.

### Verification done this session
- `flutter analyze` → clean (only the pre-existing `withOpacity` info warnings).
- `./gradlew :app:compileDebugKotlin` → **BUILD SUCCESSFUL** (the changed
  `MainActivity.kt` compiled).
- **Not yet run on the phone** (adb was flaky/asleep; no hardware run this session).

### The ONE thing left to confirm on-device (start here) ⏭️
Two re-entry cases, only the second is uncertain:
1. **Screen-off / background / Activity re-create, process alive (service running):**
   link should now **stay up** — this is what the fix targets. Verify frames +
   sonar keep flowing with the screen off and after reopening.
2. **Full process kill (swipe from recents), then cold relaunch:** the callback
   dies with the process (unavoidable — no app can hold a specifier network past
   its own death), so the app re-requests on launch. **Whether ColorOS silently
   reconnects via the remembered specifier approval or re-shows the consent is
   OS-dependent — confirm with logcat:**
   ```
   adb logcat -c
   # kill from recents, relaunch
   adb logcat | grep -Ei "WifiNetworkFactory|NetworkRequest|PiWifiService|pi_wifi"
   ```
   - If it silently reconnects → done.
   - If it re-prompts on every cold start → acceptable-ish (only on full kill,
     not backgrounding), but the clean fix is to **also register a
     `WifiNetworkSuggestion`** for SmartCane-Cam on first success: suggestions
     persist across app restarts and auto-connect via a one-tap *notification*,
     no per-launch dialog. (Tradeoff: less deterministic than the specifier;
     evaluate on-device before adopting.)

Do **not** re-add any teardown of the request on screen/Activity destroy — that
is the exact bug that was just removed.

---

## 3. ColorOS gotcha we hit + the ONLY recovery that worked ⚠️

This ate most of an earlier session. **Document it for the thesis "known limits"
and so it's never re-diagnosed from scratch.**

**What happened:** the user mis-tapped **"Don't ask again"** on the two-icon
consent chooser and picked Oppo's **"Wireless Settings"**. That wrote a **global
preferred-activity** mapping the intent action
`com.android.settings.wifi.action.NETWORK_REQUEST` →
`com.oplus.wirelesssettings/...NetworkRequestDialogActivity` with `mAlways=true`.
From then on every consent auto-routed to Oppo's broken dialog — no way to reach
the working stock one.

**Key insight:** this default is keyed to the **intent action, NOT the app.**
That's why app-side changes can't touch it.

**What did NOT clear it (all tried, confirmed useless here):**
- App uninstall + reinstall.
- Changing the app's `applicationId` (see §4) — preference isn't keyed to the app.
- Settings → **"Reset network settings."**
- Settings → **"Reset all settings"** (ColorOS has **no** "Reset app preferences"
  item — known Realme UI limitation).
- adb `pm clear com.oplus.wirelesssettings` → **SecurityException** (shell lacks
  `CLEAR_APP_USER_DATA` on Realme).
- adb `pm reset-permissions` → **SecurityException**.
- adb `pm disable-user … <component>` → **SecurityException** (priv-app).
- adb `pm disable-user` + `enable` on the whole package → ran, but did **not**
  prune the preferred activity.

**What DID clear it (the fix):**
> **Settings → App management → ⋮ (three-dot) → Show system processes →
> "Wireless Settings" (`com.oplus.wirelesssettings`) → open it → "Set as
> default" / "Open by default" → Clear defaults.**

Only the Settings app has the privilege to call the framework's
`clearPackagePreferredActivities`; adb shell does not.

**Verify from the PC** (run before rebuilding):
```
adb shell "dumpsys package preferred-activities | grep -i -A6 network_request"
```
After the fix the `mMatch=0x100000 mAlways=true` block is **gone**; only the
plain resolver-table entries for both handlers remain (no "always" lock).

**Coach the user:** when the two-icon chooser appears, pick **"Settings"** (never
"Wireless Settings"), and only tick "don't ask again" *after* confirming
"Settings" actually connects.

### adb notes for the Realme specifically
- adb was on **wireless debugging** (`_adb-tls-connect`) and **drops when the
  phone sleeps** → prefer a **USB cable** for anything multi-step.
- **"Reset all settings" revoked USB-debugging authorization** — after it, expect
  the "Allow USB debugging?" prompt again on reconnect.

---

## 4. `applicationId` change (permanent, still in place)

[`android/app/build.gradle.kts`](../Test_app/test_app_1/android/app/build.gradle.kts):
- `applicationId = "com.smartcane.app"`  ← changed from `com.example.test_app_1`
- `namespace = "com.example.test_app_1"` ← **unchanged** (deliberate)

Because `namespace` is unchanged, the Kotlin package, `MainActivity` path, and
**all MethodChannel strings stay `com.example.test_app_1/...`** (e.g.
`com.example.test_app_1/pi_wifi`) — nothing in Dart/Kotlin needed editing.

This was attempted as a "clean identity" fix for the §3 gotcha; it did **not**
fix it (preference is keyed to the intent, not the app). Kept only because
`com.smartcane.app` is a nicer production identity. **Keep or revert — low
stakes.** Installed package on the test phone is now `com.smartcane.app`; use
that in any `adb`/`pm` command targeting the app. No Firebase/FileProvider
authorities pin the old name (checked).

---

## 5. Quick status board

| Item | State |
|---|---|
| Pi AP + `WifiNetworkSpecifier` app-scoped join | ✅ works on hardware |
| First-connect speed / home-WiFi replacement | ✅ fast, no tuning needed |
| Internet stays on mobile data during cane link | ✅ confirmed |
| **Re-join after screen-off / background / re-entry** | ✅ **fixed in code, compiles — confirm on device (§2 case 1)** |
| Silent reconnect after full process kill (swipe) | ⏳ OS-dependent — logcat check (§2 case 2) |
| ColorOS mis-tap recovery | ✅ documented (§3) |
| One-time Pi install block (`smartcane-ap` etc.) | ⏭️ still to run — see STEP2 §"One-time install" |
| Second never-seen phone test | ⏭️ pending (Definition of Done) |

**Next session:** run §2's two device checks (esp. the logcat one for cold
start). Everything code-side for re-entry is done and building.
