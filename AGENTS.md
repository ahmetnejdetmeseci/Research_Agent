# ResearchPilot Agent Instructions

Before making substantial changes, read these files in order:

1. `docs/PRODUCT.md`
2. `docs/ARCHITECTURE.md`
3. `docs/ROADMAP.md`
4. `docs/PROGRESS.md`

Treat those documents as the source of truth for product intent, architectural
boundaries, milestone order, and current state.

## Working rules

- Implement only the current milestone unless the user explicitly changes the
  scope.
- Keep every completed milestone runnable.
- Keep external source clients separate from application and domain logic.
- Keep LLM providers behind a provider-independent interface.
- Do not make domain models depend on external API response types.
- Keep future agent logic separate from source integrations.
- Prefer the simplest implementation that satisfies the active milestone.
- Do not introduce an agent framework such as LangChain without an explicit
  architectural decision.
- Add or update tests for important behavior.
- After meaningful changes, update `docs/PROGRESS.md` with the current
  milestone, completed features, exact runnable commands, verified test status,
  and next milestone.
- Do not place secrets, local databases, generated digests, or user-specific
  configuration under version control.

