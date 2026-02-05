## Summary

<!-- Brief description of what this PR does (2-3 sentences) -->

## Type of Change

<!-- Mark with [x] all that apply -->

- [ ] `feat`: New feature
- [ ] `fix`: Bug fix
- [ ] `refactor`: Code refactoring (no functional changes)
- [ ] `test`: Adding or updating tests
- [ ] `docs`: Documentation updates
- [ ] `chore`: Build/tooling changes
- [ ] `perf`: Performance improvements

## Related Issues

<!-- Link to related issues, e.g., "Closes #123" or "Related to #456" -->

## Changes Made

<!-- List the specific changes made in this PR -->

-
-
-

## Testing

<!-- How was this tested? -->

- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

### Test Commands Run

```bash
# Python
pytest --cov=mi_patrimonio

# TypeScript
npm test
```

## Checklist

<!-- Mark with [x] when completed -->

### Code Quality

- [ ] Code follows [CLAUDE.md](../CLAUDE.md) standards
- [ ] No `any` types in TypeScript
- [ ] No bare `except:` in Python
- [ ] No hardcoded secrets
- [ ] All identifiers in English

### Testing

- [ ] All tests pass
- [ ] Coverage >= 70%

### Type Safety

- [ ] `tsc --noEmit` passes (TypeScript)
- [ ] `mypy --strict` passes (Python, where applicable)

### Linting

- [ ] `ruff check .` passes
- [ ] `npm run lint` passes

### Documentation

- [ ] Code is self-documenting or has comments where needed
- [ ] PLAN.md updated if architecture changed

## Screenshots (if applicable)

<!-- Add screenshots for UI changes -->

## Additional Notes

<!-- Any additional context or considerations -->

---

**Commit Message Format** (Conventional Commits):
```
<type>(<scope>): <description>

[optional body]

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```
