# Security policy

## Supported versions

Security fixes are made on `main` and ship in the next release. The latest release is supported.

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub: open this repository's **Security** tab and select **Report a vulnerability**. Please do not open a public issue for a security report.

Each report is acknowledged and triaged. A confirmed vulnerability is fixed on `main`, released, and recorded in [CHANGELOG.md](CHANGELOG.md) once a fixed version is available.

## Threat model: the design loop executes model-generated code

The agentic design loop runs Python that language models write (the code emitter and the repair agents) inside a headless Blender process, with the privileges of the user who launched it. The loop checks the code's structure and the rendered result, but it does **not** sandbox that execution. Treat generated code as untrusted:

- Run the loop under a dedicated, unprivileged account, or in a virtual machine or container with no access to credentials, SSH keys, or personal data.
- Keep the model endpoints local. The defaults point at an Ollama server on `localhost`; pointing the loop at a model server you do not control hands that server the ability to choose the code that runs on your machine.
- Pin model revisions. The code-emitter adapter can be pinned to an immutable Hugging Face revision so a changed upstream artifact is never pulled silently.
- Review generated geometry code before reusing it outside the loop.

The generators, FEA and fracture tools do not execute model output; they run the repository's own code on user-supplied parameters and meshes.

## Automated checks

Every change must pass the continuous-integration gate before it merges, and the same gate re-runs weekly on `main`:

- **Secrets:** gitleaks over the full git history (also available as a pre-commit hook).
- **Static analysis:** bandit on the package, and CodeQL (`security-extended`) on both the Python code and the GitHub Actions workflows.
- **Dependencies:** pip-audit against known-vulnerability databases, dependency review on every pull request, and Dependabot version and security updates.
- **Container:** a trivy scan of the image that blocks fixable CRITICAL and HIGH findings, and an SPDX software bill of materials signed keylessly with cosign.
- **Pipeline hardening:** every GitHub Action is pinned to a full commit SHA, workflow tokens are least-privilege, and the OpenSSF Scorecard assesses the repository weekly.
- **Releases:** distributions are published to PyPI through Trusted Publishing (no stored tokens, with digital attestations), and container images are signed by digest with cosign and carry SLSA build provenance.
