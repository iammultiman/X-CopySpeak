# AGENTS.md

CopySpeak: A lightwieight and modern AI text-to-speech orchestrator for Windows that reads clipboard text aloud when double-copied. Stack: Svelte 5, Tauri 2.

## Rules

- Fix causes, not symptoms. Report adjacent problems, don't fix them.
- Never stub, loosen, or comment out check to get green. Broken and loud beats silent and wrong.
- Unsure or blocked: ask. State assumptions, surface tradeoffs, push back on over-engineering.

## Workflow

- Use `i-have-adhd` skill: next action first, numbered steps, no preamble.
- Never run `bun run tauri dev` to verify change; already running. Use `bun run check && bun run test`.
- Never run checks or commit without explicit confirmation. Ask before concluding task.
- End with one concrete next step; user approves. Use shape: `If you want, I can do X next. React with ✅ to run it.` Several viable: list up to 3, one line each, best first.
- Hand-off prompts only include what next session can't access: decisions made, dead ends, ongoing states, next steps. Don't repeat AGENTS.md.
- Avoid image-previewing. Only user verifies/approves visually.
- Commits: [Conventional Commits](https://www.conventionalcommits.org/).
- Branches: squash-merge into `main`, then delete the branch (local and origin) in the same pass — never leave merged branches behind.

## Documentation

- **Public (tracked)**: README.md, CHANGELOG.md, BROWSER_EXTENSION.md, DESIGN.md (historical spec), docs/CONTRIBUTING.md, docs/engines.md, docs/profile-engine-settings.md, docs/agent-voice.md.
- **Internal (untracked)**: `docs_internal/` — start from `docs_internal/README.md` (the index). Superseded and historical docs live in `docs_internal/archive/`.

## Keeping this file current

File logs failures, not wishlist. Every line below exists because it went wrong at least once. On mistake, correction, or undocumented discovery about codebase:

1. Add one line to active failure log below, imperative, describing correct behaviour.
2. Keep specific to this repo. General advice belongs nowhere.
3. Fix is workflow not rule: put in `.agents/skills/` and link from here.
4. Include change in same commit, mention in summary.

Keep active failure log short: entries for work not in `## Active work` move to [`.agents/failure-log.md`](.agents/failure-log.md). Loaded every session; long context makes you less reliable, not more. Architecture detail outgrows usefulness: move to `.agents/architecture.md` or a skill.

## Active failure log

- Register config/history before webviews; atomically persist both with last-good backups, fail closed on unreadable data, and never start automatic cleanup after recovery or with empty startup history.
- Type component props as `let { ... }: Props = $props()`; generic `$props<Props>()` fails on clean Windows installs and can hide invalid component contracts locally.
- Preserve `browser_reading_id` from queued synthesis through batch fragments and scheduled PCM positions; never infer browser ownership from active-session state, matching text, or fragment index when Queue After Current leaves desktop audio playing.
- Report section synthesis failures globally before the synthesis guard releases playback; retry only transient failures, and never retry streamed PCM after any audio has been emitted or silently skip article text.

- Re-check cancellation after a daemon startup wait and before one-shot fallback; batch collection must poll cancellation too, since effects disable streaming playback.

- Give a local engine's bundled profile the same `effects` value its installer writes; `ProfileEffects::default()` is effects-enabled with walkie-talkie, and `allows_streaming_playback` requires `!effects_enabled`, so any bundled profile that uses the default silently loses the streaming fast path and pays whole-fragment synthesis before first audio.

- Yield PCM per native inference window in a local wrapper instead of joining the fragment first, and make every consumer loop all chunks — the one-shot path takes `next(stream(...))`, which silently truncates once `stream` yields more than once.

- Warm the active engine after `set_active_profile` and `set_config`, not only in the Tauri `setup` hook; otherwise the first reading after a profile or voice change pays the full cold model load.

- Never resolve a wrapper's data directory from `__file__`; pass it explicitly (`--voices-dir`). A legacy profile launched the wrapper by a CWD-relative path, so `Path(__file__).resolve().parent.parent` became the app install dir and Piper reported "voice model not found ... Available: []".

- Promote a legacy `Local` preset to its first-class engine variant when the engine gains one; only Pocket had a promotion, so Piper profiles kept running the generic CLI path with no daemon and a stale args_template.

- Pin the header style for a container-sniffing TTS reply; Gemini 3.8 unary returns `audio/wav` while 2.5/3.1 returned headerless PCM, so wrapping unconditionally double-headers the file.

- Frame a Gemini TTS request as read-aloud, and only inline for pre-3.8 models; `systemInstruction` covers all of them, but 3.8 treats the text part as a verbatim transcript and will speak an inline instruction out loud.

- Verify the pinned Edge client against upstream before declaring a refusal unfixable; 7.3.1 supersedes the 7.2.8 host workaround. Keep 429 cooldown state outside per-reading backends, preserve server Retry-After across cancellation, cap it (a header is not a licence to disable the engine for the process lifetime), and never log raw Edge subprocess output. Treat a 429/403 as final for that request: the command layer's retry otherwise turns one throttled reading into three strikes on a shared cooldown. Exempt the Engines-page health check from abort flags, which a Stop leaves set until the next reading.
- Repair only the managed Piper uv project's known relative wrapper at launch; an already-applied migration cannot repair newly imported legacy profiles, and --project alone does not relocate a relative script. Refresh installed wrappers separately without deleting voices.
- Hold Edge's request lock through both audio and sidecar reads; setup probes share those files. Cap fallback cooldowns at 60 seconds, and preserve start spacing on success instead of restarting it at completion.

- Release the old browser reading before asking the document to capture its replacement; a later disconnect erases the new paragraph/selection anchor.
- Key the browser session's eager failure finish off whether anything was audible (`active_fragment != NO_FRAGMENT`), not off `speak_queued` returning `Err`: `finish_session` is first-wins, so ending it at the first error marks the reading failed but also tears the companion bar and word highlights off the page while buffered fragments are still speaking.
- Scan every retry signal in a synthesis error instead of returning on the first status token: edge-tts pairs `NoAudioReceived("No audio was received...")` with the refused handshake's `403`, and a first-token-wins classification read the `403`, called it permanent, and skipped the retry the phrase list existed to allow.
- Flatten a reqwest error's `source()` chain into the message at every provider request site; reqwest's `Display` prints only the kind (`error sending request`), so a timeout or a dropped connection stringifies to a bare kind and the retry classifier cannot see the cause.
- Judge the browser session's eager failure finish on delivered audio as well as audibility (`delivered` flag plus `active_fragment != NO_FRAGMENT`): a fragment can reach the frontend and fail before its first throttled progress report, and `finish_session` is first-wins, so finishing on audibility alone still tears the bar off under audio about to speak. Mark `delivered` in the existing `audio-fragment-ready`/`audio-stream-chunk` Rust listeners, never from a frontend IPC acknowledgement: Tauri runs Rust listeners synchronously inside `emit`, so that happens strictly before the failure is classified, whereas an acknowledgement can arrive after the irreversible decision.
- Pass Kokoro exporter options by their long names through `Invoke-Uv`; PowerShell binds `-o` as an ambiguous common parameter before uv runs.
- Carry the browser reading's id through start, progress, delivery and finish, and resolve every one by that id; `sessions.values().next()` picks an arbitrary session once a reconnect leaves a second one registered, so an old reading could be served by the new reading's reports. Retire superseded sessions on start rather than relying on there being only one.
- Guard the browser reading's lifecycle EVENT HANDLERS, not its terminal reporter: a retrigger in Interrupt mode aborts the previous playback while the new reading is still silent, and `synthesis-state-change: false`, `playback-stop` and `synthesis-aborted` then complete the empty queue or call `handleStop`, which used to tear the new session down before its first fragment. Leave the report itself unconditional so an explicit Stop can still end a silent session.
- End the browser session from the stop commands themselves (`stop_speaking`, `abort_synthesis`, the tray abort) via `end_active_browser_reading`; `do_abort_synthesis` is shared with the retrigger path, which must NOT close the reading that replaces it, so the distinction cannot live inside it. The frontend cannot tell a user Stop from retrigger teardown for a silent reading.
- Export Kokoro's duration-capable model under isolated Python 3.12; Kokoro 0.8.4's NumPy 1.x dependency cannot use the managed engine's Python 3.13 wheels.
- Check credential presence without printing `.env` values; never grep secret files into command output.
- Round estimated caption milliseconds once, after accumulating sentence offsets; rounding per sentence and then offsetting re-rounds sentence-boundary pairs apart by 0.1 ms, and that `start_ms < audio_end` clears the whole reading's captions.
- Route playback speed and pitch through `TimeStretcher` (SoundTouch `pitch` setter, then `stretch.tempo = speed / pitch`); keep `playbackRate` at 1 on PCM sources and track `ScheduledPosition` duration/offset/rate in native time.
- On a rate change, re-stretch the native chunks of unstarted PCM sources; audio already rendered keeps the rate it was rendered at, since absolute start times do not move.
- Give `TimeStretcher`'s first output after every reset a ~5 ms fade-in, and hold the last ~5 ms of input out of the WSOLA feed for flush to release decaying; a cold-start full-amplitude sample or a hard speech-to-silence flush step clicks at fragment seams. Re-feeding a faded copy of the tail is not enough - the backward jump clicks too.
- Drive HUD captions from the audible fragment's audio clock; synthesis events may describe a later fragment, and incoming PCM chunks must not resume a user-paused stream.
- Update `play-page.svelte`'s browser mock config when adding required `AppConfig` fields, matching backend defaults.
- Re-sync `playbackStore` from its own `config-changed` listener; pages that only `set_config` (Effects page, `set_active_profile`) never update it, so previews and readings play the values the store held at startup until restart.
- Treat `git diff --check` as a check; do not run it before explicit confirmation.
- Local engine wrappers speak daemon protocol v2 (`READY 2`); emit 16-bit signed LE PCM, since `pcm-stream.ts` drops any other `bits_per_sample`.
- Gate streaming playback off when the active profile has an effect: warm local daemons stream via `CliTtsBackend::supports_streaming`, so `streaming_enabled: true` sends kokoro/piper as `audio-stream-chunk` too, and the PCM scheduler has no effect chain — only the `audio-fragment-ready` fragment path applies effects.
- Adding a `TtsEngine` variant: also update the catalog test's engine list and entry count, and the `Record<TtsEngine, number>` fixtures in `html-templates.test.ts` and `html-export.test.ts`.
- Register CUDA DLL directories with `os.add_dll_directory` inside the wrapper (Python 3.8+ ignores `PATH` for extension-module dependencies, so setting it from Rust does nothing), and prepend the same directories to `PATH`: onnxruntime loads `cudnn64_9.dll`/`cublas64_13.dll` with plain `LoadLibrary`, which ignores `add_dll_directory`; missing this fails hard with "Invalid handle. Cannot load symbol cudnnCreate".
- Pin torchaudio beside torch in CUDA profiles (same version, same cu126 index): qwen_tts imports torchaudio, and unpinned PyPI torchaudio (2.11) next to torch 2.8.0+cu126 dies at `import torchaudio` with "[WinError 127] The specified procedure could not be found" — `_torchaudio.pyd` asks the older torch ABI for symbols it does not export. Windows cu126 wheels bundle the CUDA DLLs in `torch\lib`; the Linux-only nvidia-* wheels are never the answer here.
- Emit the streaming `is_final` marker on the last fragment only; an intermediate one arms the player's completion timer mid-passage.
- KittenTTS 0.8.1 (the pinned wheel) takes only `KittenTTS(model_name, cache_dir)`; select the GPU by replacing `tts.model.session`, not with a `backend=` kwarg that only exists on `main`.
- Map browser caption words onto the raw selection with `text_map::align`'s word alignment; never re-derive the sanitizer's rewrites in a second place, and keep the highlight verdict per word and per fragment rather than per reading.
- Pass `uv init` its target directory positionally (`uv init --bare --name X <dir>`); uv 0.12+ hard-errors on `uv --project <dir> init`, which only shows up when creating a fresh engine project.
- Allow `createWaveShaper` only as a directly called member; keep rejecting local declarations and every other symbol containing "shape".
- Double-copy and browser readings run `speak_queued`; Play page, hotkey and control server run `speak_now`. Change both paths together (saved-audio replay, `reading-started`).
- Route `pagination:complete`/`pagination:stopped` to whichever player owns playback (`_pcmScheduler` vs `_fragmentQueue`), never both: during PCM streaming the fragment queue is empty, so signalling it clears the scheduler mid-drain.
- `FragmentQueue::clear()` leaves `stop_flag` set; every new `speak_queued` reading must call `clear_stop_flag()`, or the first Stop/Abort silences all later double-copy and browser readings until restart.
- `FragmentQueue::markComplete()` only completes when the queue is drained and is a no-op otherwise; use it for stop/abort and as a `synthesis-state-change: false` safety net (a mid-reading synthesis failure emits neither `is_final` nor `pagination:stopped`, so a starved queue would otherwise hang).
- Reset the queue's final-marker when the reading's first fragment (`index === 0`) is enqueued, not on a separate new-reading event: clearing mid-playback lets an in-flight fragment's `ended` handler drop the next reading's audio.
- Own the pause toggle in exactly one place: the backend `toggle_pause` command emits `playback-toggle-pause` and the store applies it. A caller that also toggles the store cancels itself out over the IPC round-trip.
- `speak_queued` never assembled or cached its audio, so `replay_cached` replayed a stale `speak_now` reading or the last fragment; concat the fragments and `cache_audio` the whole reading before `pagination:complete`.
- `SetCurrentProcessExplicitAppUserModelID` is `unsafe` in windows-rs 0.58 and takes a `PCWSTR` (`Param<PCWSTR>` is not implemented for `&HSTRING` in windows-core 0.58); bind the `HSTRING` to a local and pass `PCWSTR(app_id.as_ptr())` inside `unsafe`.
- Keep an unbreakable token whole up to `TOKEN_HARD_CAP` (4096) in `force_split_ranges`; the clause-delimiter fallback must include CJK punctuation (`，。！？、：；`), since CJK has no inter-word whitespace to snap to.
- Treat a period as intra-token only when a word character follows it, or (trailing) when it closes an initialism (`U.S.A.`, `Ph.D.`); a trailing period after a normal word (`too.`) stays a sentence boundary.
- `bun run test` fails in a bare Linux container with "Could not resolve 'node:module'" until `svelte-kit sync` has generated `.svelte-kit/tsconfig.json`; run it first (the `check` script does).
- `hud:*` events fire only while the HUD is enabled; main-window UI reads `playbackStore.caption` and `reading-started`, never HUD events.
- The browser pipe serves one client at a time; the native host retries `ERROR_PIPE_BUSY` with `WaitNamedPipeW` instead of failing the reading.
- Start the browser session's state ticker at accept time, not after `speak_queued` returns; `speak_queued` awaits the entire synthesis loop, so a post-synthesis ticker pins the companion panel at `buffering` for the whole generation while audio already plays.
- Filter Kokoro's misaki phonemes through the model vocab before inference; misaki emits unpronounceable punctuation (an unbalanced `[`) as a literal phoneme, and only a missing _letter_ phoneme is a real pronunciation gap worth aborting on.
- Captions dying on every surface at once means the active engine's provider stopped emitting timing metadata, not a broken pipeline: check `%APPDATA%/CopySpeak/logs` for "Disabling ... captions" and verify other engines still write `.captions.json` sidecars before touching code; guard ElevenLabs drift by running the `#[ignore]`d `live_caption_probe` (`cargo test live_caption_probe -- --ignored --nocapture`) before releases.
- The app loads secrets from `<exe-dir>/.env` (`src-tauri/target/debug/.env` in dev), not the repo-root `.env`; diagnose key/quota questions against the file the log line names.
- ElevenLabs with-timestamps streams carry alignment on the leading record(s) and stream later records as audio alone; treat audio-only records after an aligned one as normal, and hard-degrade only when no aligned record ever arrives.
- `bun run bump` derives the new version only from `src/lib/version.ts`; a stale version.ts under-shoots every file and `No version string found` means that file already carried the target — verify all seven ✅ lines after bumping (app files + README + browser-extension manifest and package).
- Pass `draft: true` to `softprops/action-gh-release` when attaching extra assets to tauri-action's draft release; without it the step PATCHes the matched draft with its default `draft: false` and publishes the release unreviewed.
- "Beeps" in generated audio: suspect the text before the playback code — the TimeStretcher pipeline passes silence and fuzz cleanly; ElevenLabs/Cartesia render unpronounceable glyphs (arrows, stars, math symbols, enclosed alphanumerics, private-use, control chars) as ~1 s beep artifacts, so keep `remove_unpronounceable`'s symbol ranges ahead of what vendors confound.
- Run `rustfmt` only on touched Rust files; `cargo fmt --all` marks unrelated CRLF-tracked Rust files modified on this Windows worktree.
- Bundle each installer wrapper directory in `tauri.conf.json`; bundling `install-*.ps1` without its sibling Python wrapper breaks app-driven installs in both dev and release builds.
- Run Engines-page health checks in one-shot mode; daemon prewarming plus the immediate fallback launches two copies of large local models.
- Pass the install dialog's GPU-runtime choice as `-Cuda`; a CUDA profile cannot run against the default CPU-only engine install.
- Keep the cu126-index CUDA setup Windows-only in `Add-CudaRuntime`: on Linux PyPI torch 2.8.0 already IS the CUDA build (nvidia-* wheel deps), so the `install-*.sh` ports pin plain PyPI torch/torchaudio and must not grow a custom index.
- On Linux launch with `GDK_BACKEND=x11` and show() the HUD window before `set_position`: Wayland toplevels cannot self-position (tao's set_position → gtk_window_move is silently ignored), and an X11 move only sticks once the GdkWindow is realized.
- Hide the HUD's native window when the frontend emits global `hud:stop` on Linux: webview playback never trips the Rust AudioPlayer monitor, so without this listener the HUD stays mapped after audio ends (Windows keeps the parked-window design and JS-only hide).
- Run frontend tests as `bun run test` (vitest); bare `bun test` uses bun's built-in runner without the vitest DOM environment and fails ~39 document-dependent tests that pass in CI.
- Send installer voice ids as one comma-joined `-Voices` argument and split them with `ConvertTo-VoiceIds`; `powershell -File` binds neither `-Voices a,b` nor `-Voices a b` as an array.
- Treat a Windows-green `cargo check` as silent about `cfg(not(windows))` code: before deleting an "unused" import, grep the file for that trait's methods inside cfg-gated blocks — the Linux-only `hud:stop` listener needs `tauri::Listener` (cfg-gate the import itself), and only the Linux CI build catches its absence.
- Drop CPU `onnxruntime` from GPU engine projects with `[tool.uv] exclude-dependencies`, then `uv sync --reinstall-package onnxruntime-gpu`; kokoro-onnx/kittentts/piper-tts require it transitively (so `uv remove` is a no-op), and both wheels write the same `onnxruntime/` files.
- Wrapper fixes reach an existing engine only when its installer re-runs (wrappers are copied into `engines/<name>/scripts` at install time); when a log shows a fixed failure, diff the installed wrapper against `scripts/<engine>/` first.
- Backport shared wrapper fixes to every engine's wrapper, not just the one that failed: the kokoro wrapper shipped without the PATH-prepend half of the CUDA DLL fix (kitten/qwen had it), and `--device cuda` died on `cudnn64_9.dll` even though the wheel carried it — `diff` engine wrappers against each other when touching a function they share.

<!-- rtk-instructions v2 -->

## RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has dedicated filter, it uses it. Else passthrough unchanged. RTK always safe. No `rtk bun`; see commands.

**Important**: Even in command chains with `&&`, use `rtk`:

```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

Full command reference (which tools have dedicated filters, and their savings): the `rtk-commands` skill in `.agents/skills/rtk-commands/`.
<!-- /rtk-instructions -->
