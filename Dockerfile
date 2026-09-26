# syntax=docker/dockerfile:1
# =============================================================================
# Container image for agentic-bioinspired-cad (core / pure-Python path).
#
# Installs the package with its core + dev dependencies on a slim Python base,
# so the generator geometry math, the manufacturability gate, the agent-loop
# control logic (exercised with test doubles), the evidence-record checks and
# the test suite run in a reproducible container. This is the image CI builds,
# scans, smoke-tests and signs, and the one the release pushes to GHCR.
#
# Intentionally NOT in this image: Blender, the conda CAD/FEA environments
# (CadQuery, SfePy), MOOSE, Ollama and the model weights. They are host-side
# engines driven by subprocess from the package; see README "Installation".
# =============================================================================
FROM python:3.14-slim

# OCI metadata. `source` links the published GHCR package to this repository.
LABEL org.opencontainers.image.title="agentic-bioinspired-cad" \
      org.opencontainers.image.description="Local agentic LLM-to-CAD-to-FEA-to-print loop for single-material, damage-tolerant bioinspired architectures (core image)" \
      org.opencontainers.image.source="https://github.com/crentb/agentic-bioinspired-cad" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.authors="Cameron B. Renteria"

# --- 0. Apply Debian security updates ----------------------------------------
# The python:*-slim tag is rebuilt on Docker's own cadence, so a freshly pulled
# base can still contain OS packages for which Debian has ALREADY published
# fixed versions. The CI container gate blocks fixable CRITICAL/HIGH findings,
# so upgrading here closes the window between Debian shipping a fix and Docker
# rebuilding the base. `upgrade` (not `dist-upgrade`) keeps this to in-place
# version bumps within the stable release: nothing is added or removed.
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/*

# Reproducible, quiet Python: unbuffered output, no .pyc files, no pip cache.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# --- 1. Install metadata first for better layer caching ----------------------
# (pyproject reads README.md for the long description, so it must be present.)
COPY pyproject.toml README.md LICENSE NOTICE ./

# --- 2. Package sources, shipped data, evidence records and tests ------------
# data/ holds the retrieval corpora and exemplar scripts the loop grounds on;
# results/ holds the text evidence records the gold tests re-verify.
COPY abcad/ abcad/
COPY data/ data/
COPY results/ results/
COPY tests/ tests/

# --- 3. Install the package with dev extras (core deps only) -----------------
# jaraco.context is raised explicitly because the version vendored by older
# setuptools releases carries a known advisory that the image scan would flag.
RUN python -m pip install --upgrade pip setuptools wheel "jaraco.context>=6.1.0" \
 && python -m pip install -e ".[dev]"

# --- 4. Drop root ---------------------------------------------------------------
# Nothing in the image needs root at run time. A fixed, unprivileged UID owns
# the working tree so pytest can write its cache and temporary outputs.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin abcad \
 && chown -R abcad:abcad /app
USER abcad

# --- 5. Default command: run the fast suite to prove the image works ---------
CMD ["pytest", "-m", "not slow"]
