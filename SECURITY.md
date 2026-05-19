# Security Policy

Report security vulnerabilities privately via [GitHub Private Vulnerability Reporting](https://github.com/samxli/PubVox/security/advisories/new).

## Hugging Face Spaces

The Hugging Face Spaces deployment uses a single shared local user with no authentication. Be aware of the following:

- **Make your Space private** if you upload any books you do not want publicly accessible. Use `python scripts/deploy_hf.py --repo-id <username>/pubvox --private`.
- **Persistent storage** is required to retain your library; without it, data is lost when the Space sleeps or restarts.
- **Environment variables** (e.g. TTS credentials) should be set as Space secrets rather than committed to the repository.
