# TrafficTwin Jeddah: one-command entry points. Everything is synthetic demand, uncalibrated.
#
#   make demo        setup + city network (unless CITY=0) + demo runs + API and viewer on :5173
#   make city        city network + 10 % weekday 24 h baseline (long: about 2 h uncached)
#   make test        ruff + pytest (demo window only, about 3 min)
#   make stop        stop servers started with `./run_app.sh --detach`
#   make movies      render every film in movies/specs/ + the showreel (needs ffmpeg, Chrome)
#                    with the offline voice-over (MOVIE_FLAGS=--no-voice for silent films)
#   make movie FILM=tahlia-street   render one film to movies/<film>.mp4
#   make voice-setup the offline TTS venv for the narration (.venv-tts, Kokoro-82M, ~1 GB)
#   make movie FILM=tahlia-street LANG=ar   the Arabic edition -> movies/<film>.ar.mp4
#   make movies-ar   every Arabic film + movies/showreel.ar.mp4 (Chatterbox, .venv-tts-ar)
#
# Variables: CITY=0 skips the 243 MB OSM download and the Tier A smoke; SEED=1; SAMPLE=0.10;
# DETACH=1 leaves the servers running in the background (used by the screenshot proof).

SHELL := /bin/bash
SEED ?= 1
SAMPLE ?= 0.10
CITY ?= 1
DETACH ?= 0
UV := uv
# Tier A network v2 (Track F, docs/network-v2.md); v1 (M1) and m2 (Track A) still build on request.
CITY_NET := data/jeddah/jeddah.v2.net.xml
V1_NET := data/jeddah/jeddah.net.xml
M2_NET := data/jeddah/jeddah.m2.net.xml

.PHONY: demo setup city-net city-net-v1 demo-runs ingest serve city city-baseline test screenshots stop clean-demo \
	movies movie showreel movies-check movies-docs voice-setup voice-setup-ar movies-ar showreel-ar

demo: setup $(if $(filter 1,$(CITY)),city-net) demo-runs ingest serve

setup:
	@command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/ (brew install uv)"; exit 1; }
	@command -v npm >/dev/null || { echo "node/npm is required (brew install node)"; exit 1; }
	$(UV) python install 3.12
	$(UV) sync --frozen
	@$(MAKE) --no-print-directory web/node_modules/.package-lock.json

# npm ci only when the lockfile changed (it wipes node_modules, even under a running Vite server)
web/node_modules/.package-lock.json: web/package-lock.json
	cd web && npm ci --include=dev --no-audit --no-fund

# Jeddah network (v2, default profile): downloads the Geofabrik GCC extract on first run, clips,
# tags untagged major roads with the measured lane/speed defaults, netconvert, fixes.
city-net: $(CITY_NET)
$(CITY_NET):
	@command -v osmium >/dev/null || { \
	  if command -v brew >/dev/null; then brew install osmium-tool; \
	  else echo "osmium-tool is required (apt install osmium-tool)"; exit 1; fi; }
	$(UV) run python -m sim.network.build_city

demo-runs:
	$(UV) run python -m sim.demo --seed $(SEED)

ingest:
	$(UV) run python -m api.ingest --all

serve:
	./run_app.sh $(if $(filter 1,$(DETACH)),--detach)

# Earlier networks, kept reproducible: v1 (M1, Tier B windows are cut from it) and m2 (Track A).
city-net-v1: $(V1_NET)
$(V1_NET):
	$(UV) run python -m sim.network.build_city --network-profile v1
$(M2_NET):
	$(UV) run python -m sim.network.build_city --network-profile m2 --out $(M2_NET) --no-side-outputs

# Long-running (documented in README): zones on the v2 network and the weekday baseline.
ZONES := data/population/zones/zones.json
city: city-net $(ZONES) city-baseline
$(ZONES): $(CITY_NET)
	$(UV) run python -m sim.population.zones
city-baseline: $(CITY_NET) $(ZONES)
	mkdir -p logs
	set -o pipefail; $(UV) run python -m sim.runner --baseline --daytype weekday --sample $(SAMPLE) --seed $(SEED) \
	  --gzip 2>&1 | tee logs/city-baseline.log

test:
	$(UV) run ruff check . && $(UV) run ruff format --check . && $(UV) run pytest -q
	cd web && npm run typecheck

# Headless Chrome screenshots of the running viewer (docs/img/final-*.png); needs `make demo DETACH=1`.
screenshots:
	cd web && node scripts/final-shots.mjs

stop:
	@if [[ -f logs/app.pids ]]; then kill $$(cat logs/app.pids) 2>/dev/null || true; rm -f logs/app.pids; echo stopped; \
	else echo "no logs/app.pids (nothing started with --detach)"; fi

clean-demo:
	rm -rf runs/demo-manifest.json data/demo-cache

# Cinematic films of existing runs (Track E, docs/movies.md). One film at a time; frames are
# deleted after encoding. MOVIE_FLAGS passes options through (e.g. --4k, --fps 60, --letterbox).
FILM ?= tahlia-street
MOVIE_FLAGS ?=
# Film language: `make movie FILM=x LANG=ar`. LANG is also the locale variable, so a LANG given on
# the command line is taken as the film language and the recipes keep a normal locale
# (TT_LOCALE, default en_US.UTF-8); a LANG from the environment is ignored (English films).
ifeq ($(origin LANG),command line)
MOVIE_LANG := $(LANG)
override LANG := $(or $(TT_LOCALE),en_US.UTF-8)
export LANG
else
MOVIE_LANG := en
endif
LANG_FLAG := $(if $(filter-out en,$(MOVIE_LANG)),--lang $(MOVIE_LANG))
LANG_TAG := $(if $(filter-out en,$(MOVIE_LANG)),.$(MOVIE_LANG))
NO_VOICE := $(findstring --no-voice,$(MOVIE_FLAGS))
TTS_PY := .venv-tts/bin/python
# Narration TTS (docs/movies.md "Voice-over"): pinned, kept out of the project lock (torch is
# large); the first run downloads the Kokoro-82M weights (Apache-2.0) into the Hugging Face cache,
# every later run is offline (HF_HUB_OFFLINE=1).
voice-setup: $(TTS_PY)
$(TTS_PY): scripts/movies/tts-requirements.txt
	$(UV) venv --python 3.12 .venv-tts
	$(UV) pip install --python $(TTS_PY) -r scripts/movies/tts-requirements.txt
	echo '[{"text": "Voice check.", "out": "/tmp/tt-voice-check.wav"}]' | $(TTS_PY) scripts/movies/tts_kokoro.py
	touch $(TTS_PY)
# Arabic narration TTS (docs/movies-arabic.md): Chatterbox Multilingual (MIT) in its own pinned venv;
# the first run downloads the weights and the ClArTTS reference clip (CC-BY-4.0), later runs are offline.
TTS_AR_PY := .venv-tts-ar/bin/python
voice-setup-ar: $(TTS_AR_PY)
$(TTS_AR_PY): scripts/movies/tts-ar-requirements.txt
	$(UV) venv --python 3.12 .venv-tts-ar
	$(UV) pip install --python $(TTS_AR_PY) -r scripts/movies/tts-ar-requirements.txt
	$(UV) run python -m scripts.movies.voice_ref_ar
	echo '[{"text": "تَجْرِبَةُ الصَّوْتْ.", "out": "/tmp/tt-voice-check-ar.wav"}]' | $(TTS_AR_PY) scripts/movies/tts_ar.py
	touch $(TTS_AR_PY)
movies-check:
	@command -v ffmpeg >/dev/null || { \
	  if command -v brew >/dev/null; then brew install ffmpeg; \
	  else echo "ffmpeg is required (apt install ffmpeg)"; exit 1; fi; }
	@$(MAKE) --no-print-directory web/node_modules/.package-lock.json
	@$(if $(NO_VOICE),true,$(MAKE) --no-print-directory $(if $(LANG_TAG),voice-setup-ar,voice-setup))
movie: movies-check
	mkdir -p logs
	set -o pipefail; $(UV) run python -m scripts.movies.render $(FILM) $(LANG_FLAG) $(MOVIE_FLAGS) 2>&1 | tee logs/movie-$(FILM)$(LANG_TAG).log
movies: movies-check
	mkdir -p logs
	set -o pipefail; $(UV) run python -m scripts.movies.render --all $(MOVIE_FLAGS) 2>&1 | tee logs/movies.log
	$(UV) run python -m scripts.movies.showreel $(NO_VOICE)
	$(UV) run python -m scripts.movies.assets
showreel:
	$(UV) run python -m scripts.movies.showreel $(NO_VOICE) $(LANG_FLAG)
# The Arabic edition of every film, one at a time, then its showreel (English films untouched).
movies-ar:
	@$(MAKE) --no-print-directory movies-check LANG=ar
	mkdir -p logs
	set -o pipefail; $(UV) run python -m scripts.movies.render --all --lang ar $(MOVIE_FLAGS) 2>&1 | tee logs/movies-ar.log
	$(UV) run python -m scripts.movies.showreel --lang ar
showreel-ar:
	$(UV) run python -m scripts.movies.showreel --lang ar
movies-docs:
	$(UV) run python -m scripts.movies.assets
