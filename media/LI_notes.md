# LinkedIn notes: Garmin Activity Map

Ten things worth knowing, as raw material for a post.

- **Own your data:** it turns a Garmin Connect account into a local JSON archive. In my case that is about 8,300 activities from 2017 to 2026, kept on my own disk instead of in the vendor's cloud.
- **One desktop map:** a PyQt6 app draws every track over OpenStreetMap at once. You can filter by date, change track color and opacity, show activity names, and pan or zoom deep into the map.
- **Polite to Garmin:** at most one request per second, plus extra delay and random jitter for detail downloads. HTTP 429 `Retry-After` is honored, and a 401/403 stops the run immediately instead of hammering the login.
- **Resumable by design:** files are written atomically, each partial download is checkpointed, and `export-state.json` records progress. A rerun downloads only what is missing, such as new activities or earlier failures.
- **Credentials stay out of the repo:** the password is only typed at runtime, never read from files or env vars. Session tokens live in `~/.garminconnect` with user-only permissions, and the tests use synthetic fixtures only.
- **Speed was measured, not guessed:** a benchmark showed the stutter came from painting full geometry, not from map tiles. The fixes were level-of-detail geometry, viewport culling, batched path drawing, and a compressed prepared-data cache. 1,000 synthetic tracks now reach first display in about 2-3 s against an 8 s budget.
- **12 quality gates in one script:** `localPipeline.sh` runs formatting, lint, strict mypy, dead code, complexity, architecture rules, docs, package build, 286 tests, at least 95% coverage, a performance budget, and CLI/GUI smoke runs.
- **CI = local:** GitHub Actions runs the exact same script, so a green badge means the same thing as a green local run. The GUI is tested end-to-end offscreen with fabricated Garmin-shaped data.
- **Hands-off releases:** a push to master checks the version, reruns every gate, tags the commit, and publishes the wheel, sdist, docs, a metrics report and SHA256 checksums as a GitHub Release.
- **Built with AI, held to a high bar:** about 10,000 lines of code in 108 commits since June 2026, every dependency pinned exactly, and GPLv3 licensed. The AI wrote the code, and the pipeline decides what counts as done.

Repo: https://github.com/marcelpetrick/GarminActivityMap
