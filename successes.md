# X-CopySpeak: User-Confirmed Fixes

## Settings Recovery From Previous Versions - 2026-11-02

After a reboot, version 0.2.15 showed a managed-state startup error and missing
settings, profiles and history. The user confirmed that restoring the data folder
to a previous Windows version restored settings. This validates that recovery
method, not a specific corruption cause or the new application fix. Restoration
of history and profiles was not separately confirmed. The preventative startup
and persistence changes in 0.2.16 still require Windows runtime validation.

## Edge Service Recovery - 2026-10-11

The user retested Edge-TTS in their existing installation and confirmed it works
again. No new installer had been delivered, so this is service recovery, not
proof that the alternate-endpoint fallback fixed their original 403.

Keep the normal endpoint first. The new fallback retries the alternate Microsoft
endpoint only after HTTP 403, preserves word-boundary captions, and discards any
partial audio from the failed attempt. Nine regression tests pass; live probes
from Codespaces obtained audio from both endpoints. Recovery through the fallback
on the user's Windows network remains unverified.

## Windows Test Results - 2026-10-09

The user tested the installed app and reported the outcomes below. The tested
version, engines, profiles, hardware, and exact sequences were not specified in
this confirmation. X-CopySpeak 0.2.11 was the latest installer delivered in this
conversation, but the confirmation alone does not establish the version tested.

| Reported issue                                      | User's test result                                       | Changes made                                                                                                                                                                                        |
| --------------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pagination split words in the middle                | Pagination splits/breakpoints were tested and were okay. | Prefer sentence and whitespace boundaries, preserve punctuation-bearing tokens up to the hard cap, split oversized tails, and use CJK clause punctuation. Honor the configured pagination settings. |
| Abort, pause, and resume were missing or unreliable | Abort, pause, and resume were tested and work okay.      | Add Pause/Resume; use one toggle owner; route Stop through shared cancellation; reset queue stop state; drain failed PCM correctly; protect queued requests from cancellation races.                |
| "On Retrigger Behavior" prevented saving settings   | Saving the setting was tested and worked okay.           | Map "Stop and restart" to the backend value `interrupt`; restrict choices to `interrupt`/`queue`; validate selected values; remove the unsupported Ignore option and add regression tests.          |
| Pinned taskbar icon disappeared                     | The icon issue appears resolved.                         | Set a process AppUserModelID matching the installer identity before creating windows; verify the ICO contains multiple sizes; retain the identity through the rebrand.                              |
| App lagged and glitched                             | Lagging/glitching appears resolved in the user's tests.  | Remove duplicate shortcut-plugin registration, throttle browser progress IPC, and correct queue/PCM completion lifecycle defects.                                                                   |
| Slow time to first audio                            | Slow startup appears resolved.                           | Emit completed paginated batch fragments immediately instead of waiting for the whole reading; pass the real pagination configuration and suppress duplicate assembled playback.                    |

These results validate the original reported symptoms within the user's tested
scenarios. They do not establish that every individual change was the cause of
the improvement, or that every additional audit finding was tested independently.
In particular, "appears resolved" remains a qualified observation for the icon,
lag/glitching, and slow-start issues.

## Reference and Remaining Coverage

- Full causes, changes, verification history, and outstanding limitations:
  [docs/issues-and-fixes.md](docs/issues-and-fixes.md).
- Implementation/build commit: `1944d59`.
- Retrigger save fix and 0.2.11 version commit: `17a6adb`.
- Prior automated checks: 81 frontend tests passed for 0.2.11; the playback
  implementation passed 286 Rust tests with one ignored live-provider probe;
  the native Windows installer build succeeded.
- This confirmation does not explicitly cover whole-reading Replay, restart
  persistence of saved settings, an in-place installer upgrade, tray-specific
  pause, every engine/effects combination, or cross-mode playback edge cases.

No application code was changed to record these results. No automated checks
were rerun solely for this documentation update.
