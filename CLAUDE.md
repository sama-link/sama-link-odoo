# Odoo Test MCP (Claude Code)

## MCP server: odoo-mcp

`.mcp.json` connects **directly over HTTP** to `https://test.sama-link.com/mcp`.
Health: `https://test.sama-link.com/mcp-health` | Database: `test_db` only
If tools fail to connect: `/mcp` → **Reconnect**, then start a new chat.

## Tool names — depends on client

| Tool | Claude **Desktop** | Claude **Code CLI** |
|------|-------------------|---------------------|
| Version | `odoo-mcp:odoo_version` | `mcp__odoo-mcp__odoo_version` |
| ORM read | `odoo-mcp:odoo_search_read` | `mcp__odoo-mcp__odoo_search_read` |
| Module info | `odoo-mcp:odoo_module_info` | `mcp__odoo-mcp__odoo_module_info` |
| List addons | `odoo-mcp:filesystem__list_directory` | `mcp__odoo-mcp__filesystem__list_directory` |
| Read file | `odoo-mcp:filesystem__read_file` | `mcp__odoo-mcp__filesystem__read_file` |

- **Desktop:** colon separator; may need `tool_search` before first call.
- **CLI:** `mcp__<server>__<tool>` underscores; start a new chat after `/mcp` reconnect.

Do **not** use bare names like `odoo_search_read`.

## P0 context (pre-verified)

- `sl_appraisal` + `sl_monthly_bonus` installed on `test_db`
- `hr.appraisal.total_score` (float) and `state` includes `hr_finalization`

## Security

- Test only — no Production/Dev Odoo
- GitHub: feature branches + PRs only
