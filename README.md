# SONGPOST

Type one line, get a finished song at its own link, send it to someone.

Built for Stranger Builds I (Frontier Tower, Sat Oct 31, 2026). First commit
after the event's opening gun: Fri Oct 30, 2026, 16:00 PT.

## What v0 does

- One page, one input: type a line ("a haunted disco song about my ex's
  houseplant"), get a song page at its own link, `/s/<slug>`.
- Every song page has a player, the prompt that made it, a feedback box,
  and a "Make your own" link. Feedback ("darker", "more drums") renders a
  new version on the same page. This is the revision loop, productized.
- A public counter on the home page: songs made, plays, feedback lines.
  The counter is derived from the files on disk on every request. It
  cannot drift from reality because it is never stored.

## How it works

Python 3 standard library only. No dependencies, no build step.

- `engine.py` — the song engine. Deterministic and sample-free: the
  prompt seeds a composition (key, mode, tempo, chord progression,
  melody walk, bass, synthesized drums), rendered to a 16-bit WAV with
  oscillators and envelopes. Same prompt, same song. Feedback starts
  from the parent song's parameters, applies plain-language changes,
  and folds the feedback text into the seed, so any note from a
  listener produces a genuinely different render.
- `server.py` — a small HTTP server: generation API, song pages,
  feedback API, play counting, and the derived stats endpoint.
  Songs live in `data/songs/<slug>/` as WAV versions plus a meta.json.
- `index.html`, `song_template.html` — the two pages, inline CSS/JS.
- `tests/test_pipeline.py` — stdlib unittest: real audio (valid WAV,
  audible, long enough), determinism, prompt sensitivity, feedback
  changing both params and audio, and counter-derivation checks.

Run it:

```sh
python3 server.py            # http://localhost:8377
python3 -m unittest discover -s tests
```

## The engine hook (next slice)

`engine.generate(prompt, feedback, parent)` is the whole contract.
NOCTURNE, the music engine this product was designed around, slots in
behind that one function: same signature, same return shape
(wav bytes plus a params dict). Swapping it in changes nothing in the
server, the pages, or the counter.

## Build notes

- Page, player, and server glue: Codex seat. First attempt on the
  system Codex failed (its install is missing the code-mode host
  binary); the fleet-local Codex install completed the slice.
- Link/slug and feedback wiring: assigned to the Grok Build seat in
  the plan; that seat lives on a machine that was off tonight, so the
  wiring shipped inside the server slice instead.
- Tests and counter checks: coordinator-written stand-ins for the
  OpenCode seat, same reason. OpenCode re-runs them Saturday.
- Deploy to songpost.heavener.co is parked: the Cloudflare CLI on this
  machine is not authenticated, and wiring DNS needs that login.
  Fix: `wrangler login` once, then deploy. Nothing about the app
  changes when that happens.
