# Third-Party Notices

uteki redistributes selected SKILL.md / agent-prompt markdown sourced from
upstream open-source projects. Original copyrights remain with their authors.

---

## anthropics/financial-services

- **Upstream**: https://github.com/anthropics/financial-services
- **License**: Apache License, Version 2.0
- **Pinned commit**: `96bc9615bccdff61c190cc3e29687f5885bc3929`
- **Distribution form**: source markdown, embedded into our skill loader at
  runtime; not redistributed as a Cowork plugin nor a Managed Agent template.

### Files derived from this project

| upstream path | local path |
|---|---|
| `plugins/agent-plugins/market-researcher/agents/market-researcher.md` | `services/api/src/uteki_api/skills/research/SKILL.md` |
| `plugins/agent-plugins/market-researcher/skills/sector-overview/SKILL.md` | `services/api/src/uteki_api/skills/research/references/sector-overview.md` |
| `plugins/agent-plugins/market-researcher/skills/competitive-analysis/SKILL.md` | `services/api/src/uteki_api/skills/research/references/competitive-analysis.md` |
| `plugins/agent-plugins/market-researcher/skills/comps-analysis/SKILL.md` | `services/api/src/uteki_api/skills/research/references/comps-analysis.md` |
| `plugins/agent-plugins/market-researcher/skills/idea-generation/SKILL.md` | `services/api/src/uteki_api/skills/research/references/idea-generation.md` |
| `plugins/agent-plugins/earnings-reviewer/agents/earnings-reviewer.md` | `services/api/src/uteki_api/skills/earnings/SKILL.md` |
| `plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/SKILL.md` | `services/api/src/uteki_api/skills/earnings/references/earnings-analysis.md` |
| `plugins/agent-plugins/earnings-reviewer/skills/morning-note/SKILL.md` | `services/api/src/uteki_api/skills/earnings/references/morning-note.md` |
| `plugins/agent-plugins/earnings-reviewer/skills/earnings-preview/SKILL.md` | `services/api/src/uteki_api/skills/earnings/references/earnings-preview.md` |

### Modifications

Each derived file carries a leading HTML-comment header naming the upstream
source path, the pinned commit, and a note describing local modifications
(e.g. addition of a Chinese-output addendum, removal of Excel-specific
references). The Apache 2.0 LICENSE applies; the local NOTICE entry above
satisfies §4(c).

### What we did NOT take

- `*/agent-plugins/*/.claude-plugin/plugin.json` — Cowork plugin manifest;
  not used by our runtime.
- `managed-agent-cookbooks/**/agent.yaml` — Managed Agents API templates;
  superseded by our own harness.
- `plugins/agent-plugins/earnings-reviewer/skills/{model-update,audit-xls,xlsx-author}/SKILL.md`
  — strong Excel dependencies; deferred until uteki ships Excel tools.
- `partner-built/**` — partner-authored content with separate notice
  requirements; not adopted.
