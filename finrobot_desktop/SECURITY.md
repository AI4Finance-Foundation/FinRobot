# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

1. **Do NOT open a public GitHub issue** for security vulnerabilities.
2. Open a [private security advisory](https://github.com/AI4Finance-Foundation/finagent/security/advisories/new) on GitHub.
3. Include: description, reproduction steps, impact assessment.
4. We will acknowledge within 48 hours and provide a fix timeline within 7 days.

## Security Considerations

### API Key Management
- Desktop V1 stores API keys through the `SecretStore` abstraction. The default backend is the operating system keychain (macOS Keychain, Windows Credential Manager, or the platform backend exposed by `keyring`).
- `FileSecretStore` is used automatically when:
  1. `FINAGENT_DEV_MODE=1` is set (explicit dev mode), or
  2. the `keyring` Python package is not installed, or
  3. the OS keyring backend is not functional (headless environments: CI, Docker, WSL without a desktop session).
  A warning is logged when the fallback triggers. Its file lives at `~/.finagent/.secrets` and must have `0600` permissions.
- Non-sensitive settings such as model name, SEC user-agent, and log level may be stored in `~/.finagent/settings.json`. API keys must not be stored there.
- Supported secret keys: `anthropic_api_key`, `deepseek_api_key`, `openai_api_key`, `fmp_api_key`, `finnhub_api_key`.
- `GET /api/settings` never returns API key plaintext. It only returns `*_api_key_set: true/false`.
- Keys must never be logged, included in error messages, cached in analysis artifacts, or persisted in frontend state/localStorage.
- `.env` variables remain supported for CLI/development compatibility, but the desktop settings flow should use `/api/settings` and `SecretStore`.

### Local Server
- FastAPI server binds to `127.0.0.1:8000` by default (localhost, local-only).
- To run the server: `finagent serve --host 127.0.0.1 --port 8000`
- **Do not expose to the internet without authentication middleware.** The server has no built-in authentication.
- The `--host` option allows customization for advanced setups (e.g., Docker containers), but the default is intentionally restrictive.

### Data Cache
- Financial data is cached in local SQLite (`finagent_cache.db`, gitignored).
- Cache contains market data, financial metrics, and analysis results — **not credentials or API keys.**
- Cache is stored locally on the user's machine and is not synced to cloud services.
- Cache database uses Write-Ahead Logging (WAL) mode for concurrent access safety.

### LLM Data Flow
- Financial data (company financials, valuation metrics, peer comparables, research analysis) is sent to the configured LLM provider for synthesis and narrative generation.
- **Review your LLM provider's data retention and privacy policy:**
  - **Anthropic Claude**: Check https://www.anthropic.com/privacy
  - **OpenAI**: Check https://openai.com/privacy
  - **DeepSeek**: Check the DeepSeek privacy terms for your region
  - **Finnhub/FMP**: Real-time market data providers — check their privacy policies
- No data is sent to services other than the configured LLM provider and the optional data enrichment providers (FMP, Finnhub, SEC EDGAR).
- SEC EDGAR data is fetched from a US government public database; see https://www.sec.gov/privacy.html.

### Dependencies
- FinAgent uses widely-maintained libraries with known security practices:
  - **PydanticAI** (Pydantic): Structured AI output handling
  - **FastAPI**: REST API framework with built-in security modules
  - **httpx**: Async HTTP client for external API calls
  - **yfinance**: Yahoo Finance data provider (market data only)
  - See `pyproject.toml` for the full dependency list.
- Keep dependencies up to date with `pip install --upgrade -e ".[dev]"`.

### Local Development Only
- The reference architecture (this repository) is designed for local development and single-user deployment.
- For multi-user or production deployment scenarios, you **must**:
  - Add authentication middleware (e.g., OAuth, API keys)
  - Use HTTPS/TLS for all network communication
  - Implement rate limiting and request validation
  - Audit all financial data flows
  - Consider a reverse proxy (nginx/Caddy) for additional security layers
  - Review your cloud provider's security guidelines if deploying to cloud infrastructure

### Responsible Use
- Financial analysis produced by FinAgent is **generated with LLM assistance** and should be validated before use in real investment decisions.
- FinAgent is not a replacement for professional financial advice.
- Always cross-check LLM-generated valuations and recommendations with primary sources.
- Understand the limitations of simplified valuation models (DCF, comps) as implemented in this tool.

## Security Updates

Security patches will be released as needed. Users are responsible for keeping FinAgent updated. To check for updates:

```bash
pip install --upgrade finagent
```

Subscribe to GitHub release notifications (Watch → Releases only) to stay informed of security releases.
