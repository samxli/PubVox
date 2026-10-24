# Security Policy

Report security vulnerabilities privately via [GitHub Private Vulnerability Reporting](https://github.com/samxli/PubVox/security/advisories/new).

## Hugging Face Spaces

See [HF_DEPLOY.md](HF_DEPLOY.md) for deployment details. The Hugging Face Spaces target serves a single shared library. Be aware of the following:

- **Set `PUBVOX_PASSWORD`** as a Space secret so protected API routes and chapter audio require the password, especially if the Space is public. `/api/login` and `/api/health` stay public, and anyone with the shared password has full access to the library.
- **Make your Space private** if you upload any books you do not want publicly accessible. Use `python scripts/deploy_hf.py --repo-id <username>/pubvox --private`.
- **Persistent storage** is required to retain your library; without it, data is lost when the Space sleeps or restarts.
- **Environment variables** (e.g. TTS credentials) should be set as Space secrets rather than committed to the repository.
