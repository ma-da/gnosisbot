# Gnosis.bot Development Instructions

These instructions apply to all development agents, contributors,
implementation packages, feature additions and production hotfixes.

## 1. Development Philosophy

- Prioritize security, reliability, simplicity and maintainability.
- Preserve existing working functionality.
- Inspect current source before proposing or implementing changes.
- Do not assume that earlier source snapshots remain current.
- Avoid unnecessary infrastructure, dependencies and abstractions.
- Prefer incremental, modular and independently testable changes.
- Document important architectural decisions and limitations.
- Do not introduce paid API calls without explicit authorization.

## 2. Production Infrastructure

Current production architecture:

- DigitalOcean Ubuntu droplet
- FastAPI / Uvicorn
- Python 3.12 managed through uv
- SQLite
- Caddy reverse proxy
- systemd services
- Application directory: /opt/gnosis
- Python environment: /opt/gnosis-venv
- Primary service: gnosis.service
- Production domain: https://gnosis.bot

Preserve this architecture unless a demonstrated requirement
justifies changing it.

Do not introduce Postgres, Redis, Docker, Kubernetes or additional
persistent services without explicit approval.

Do not install unnecessary development or testing infrastructure
on the production server.

## 3. Git Workflow

Repository: https://github.com/ma-da/gnosisbot

Branches:

- development: active development and integration
- main: validated stable releases

Normal development targets development.

Direct production alpha hotfixes are permitted. Synchronize these
changes back to development promptly.

Before committing:

- Inspect current repository status.
- Review staged files.
- Preserve unrelated changes from other development threads.
- Exclude private data, credentials and temporary backups.
- Include associated tests and dependency changes.

Do not force-push or rewrite published history without explicit
authorization.

Do not pull divergent changes directly into the live application
directory without reviewing their impact.

Do not merge failing releases into main.

## 4. Regression Test Maintenance

Before implementing any feature, refactor or hotfix:

- Inspect the existing regression tests on development.
- Inspect .github/workflows/ci.yml.
- Identify tests affected by the proposed changes.
- Include necessary test updates in the implementation package.
- Add meaningful tests for new functionality.

When application architecture or behavior intentionally changes,
update obsolete test expectations accordingly.

Never delete, disable or weaken meaningful regression coverage
simply to make CI pass.

Preserve and extend tests covering:

- Authentication and authorization
- Account and data isolation
- Financial and credit integrity
- Database migrations
- Quantum circuit and artifact integrity
- Reading execution and completion
- Privacy and security
- Frontend layout and behavior
- Contact submission protection

Run applicable tests in an isolated environment when available.

Explicitly report any tests that could not be executed.

GitHub Actions is the authoritative full regression environment.

Existing release verification commands:

    python -m pip check
    python scripts/test_release.py
    python scripts/verify_quantum.py

Current CI runtime baseline:

- Python 3.12
- Node.js 22

Application changes and corresponding test updates should be
committed and pushed together.

Resolve failed regression checks before merging into main.

## 5. Dependency Management

Every new third-party dependency must be declared in the repository.

- Runtime Python dependencies belong in requirements.txt.
- Test-only dependencies belong in requirements-dev.txt.
- Use versions compatible with the production environment.
- Update dependency declarations in the same commit as the code
  requiring them.
- Do not assume a package installed on production is available
  in GitHub Actions.
- Ensure a clean environment can reconstruct the application
  from repository files alone.

Avoid adding dependencies when existing libraries or Python
standard-library functionality are sufficient.

## 6. Frontend Architecture

Maintain the consolidated frontend architecture.

- style.css: shared public styles
- account.css: account dashboard styles
- Existing page-specific CSS: specialized page styling
- Existing admin CSS: administrative interface styling

Do not introduce additional incremental override stylesheets
without a clear architectural justification.

Prefer modifying existing relevant stylesheets.

Maintain brand consistency:

- No decorative gradients
- No unnecessary border radii
- Clean, compact layouts
- Strong typography
- Minimal decorative containers
- Consistent headers, navigation and footers
- Responsive desktop, tablet and mobile layouts

Preserve the established visual design unless a redesign is
explicitly requested.

Self-host fonts, scripts and frontend libraries.

Do not introduce unnecessary external CDN dependencies.

Preserve keyboard accessibility, focus management, semantic HTML,
reduced-motion support and Content Security Policy compatibility.

## 7. Account Dashboard

Preserve the existing Quantum Portal Dashboard.

Maintain existing functionality including:

- Account key authentication
- Credit balances and purchases
- Active reading requests
- Reading history
- Communications
- Wallet integration
- Workspace and collaboration features
- Quantum authenticity certificates

Integrate new account features into the existing experience
rather than creating disconnected applications.

Avoid increasing dashboard clutter.

Complex new functionality may use dedicated views within the
authenticated account experience.

## 8. Backend and Database

SQLite remains the primary datastore.

- Use additive, versioned migrations.
- Inspect existing migration numbers before assigning new ones.
- Never modify an already-applied migration casually.
- Preserve backward compatibility where practical.
- Use atomic transactions for related state changes.
- Keep write transactions short.
- Do not hold database transactions open during external API calls.
- Enforce authorization server-side.
- Use parameterized SQL.
- Make critical operations idempotent.

Financial, credit and inventory changes must be auditable
and reconcilable.

Back up production data before applying consequential migrations.

Test migrations against isolated databases.

## 9. Event-Driven Processing

Prefer durable event-triggered processing over recurring polling.

Examples include:

- Reading completion
- Certificate issuance
- Completion notifications
- Inventory state changes
- Account communications
- Attestation and profile lifecycle events

Prefer post-commit events and persistent outbox records.

Design for:

- Idempotency
- Explicit retry handling
- Crash recovery
- Duplicate prevention
- Observable failure states
- Manual recovery when appropriate

Do not add fixed-interval workers merely for convenience.

External confirmation workflows may use bounded polling when
technically necessary.

## 10. Quantum Integrity

Preserve the distinction between:

- Quantum Future
- Quantum Past
- Classical readings
- Quantum random-number generation

Do not misrepresent historical results as newly executed
quantum computations.

Preserve existing quantum circuit artifacts, provenance records,
hardware metadata and verification requirements.

Do not modify validated quantum circuits or interpretation of
quantum measurement data without explicit authorization and
appropriate verification.

Maintain the signed inventory and Bitcoin verification system.

Verified reserve inventory is not degraded simply because it
has not been released into available inventory.

Preserve inventory enforcement and credit settlement safeguards.

Do not submit paid quantum jobs during regression tests.

## 11. Security and Privacy

Never commit:

- Production environment files
- API credentials
- Private keys
- Account key files
- Recovery secrets
- Invitation or claim codes
- Production databases
- Private quantum inventory
- Private contact records
- Protected user evidence
- Temporary production backups

Use least privilege.

Enforce authentication and authorization on every protected
backend operation.

Preserve existing account session protections and origin checks.

Do not expose private information through logs, health endpoints,
administrative summaries or public API responses.

Use encryption for sensitive stored data as appropriate.

Do not introduce third-party tracking, browser fingerprinting
or IP-based contact protection without explicit approval.

Preserve the existing contact submission protections, including
signed form tokens, minimum completion time, request-size
limits, rate controls and encrypted quarantine.

## 12. Identity and Secure Profiles

The identity network must remain distinct from ordinary
Gnosis account authentication.

Follow the approved profiles.md development plan and
identity-network protocol specification.

Core requirements:

- Stable identities independent of wallet addresses
- Private-by-default profiles
- Verified adult eligibility before profile creation
- Separate 18+ and 21+ attestations
- Versioned identity and credential records
- Explicit disclosure controls
- Multiple wallet bindings
- Human-gated ownership recovery
- Audited evidence access

Do not give the normal web application unrestricted ability
to decrypt identity documents.

Keep identity evidence encryption, authority signing,
account authentication and blockchain transaction keys separate.

Identity recovery must not silently transfer Gnosis account
credits, reading histories or other account assets.

Do not activate sensitive document collection or ownership
recovery before the required security controls are validated.

## 13. Deployment and Implementation Packages

Production changes should be reproducible and reversible
where technically possible.

For substantial updates, prefer implementation packages with:

- README and installation instructions
- Source compatibility checks
- Preflight or dry-run mode
- Explicit list of affected files
- Backup procedures
- Migration instructions where required
- Relevant regression tests
- Post-installation verification
- Recovery or rollback instructions

Installers must not silently overwrite unrelated production changes.

Fail safely when source compatibility checks detect unexpected
changes.

Prefer copy-paste shell commands and Python modification scripts
over instructions requiring interactive terminal editors.

Keep backups outside tracked source directories.

Restart only services that actually require restarting.

Static frontend and test-only changes generally do not require
application service restarts.

## 14. Operational Health

Health indicators must reflect actual system state.

Distinguish:

- Operational
- Degraded
- Unavailable
- Not verified
- Intentionally disabled
- Awaiting external confirmation

Do not represent a configured capability as operational
without appropriate evidence.

Do not expose sensitive administrative information through
public health interfaces.

Prefer current status data fetched on demand rather than
unnecessary continuous monitoring requests.

## 15. Development Handoffs

When starting a new development session:

1. Read AGENTS.md.
2. Inspect current source and repository state.
3. Review relevant tests and dependency declarations.
4. Identify affected interfaces, migrations and workflows.
5. Preserve changes from other development threads.
6. Implement the smallest complete solution.
7. Provide verification and deployment instructions.

For substantial work, document:

- Changes made
- Files affected
- Tests updated
- Tests executed and their results
- Dependencies added or changed
- Database changes
- Security implications
- Deployment requirements
- Remaining limitations

Do not claim successful testing or production verification
unless it actually occurred.

## 16. Instruction Precedence

Explicit current project-owner instructions take precedence over
these standing development preferences.

If a requested change conflicts with an established security
or integrity requirement, identify the conflict before
implementing it.

When approved architectural decisions change, update this
document alongside the relevant implementation.
