# Clean Ubuntu 26 acceptance checklist

Run against the candidate `.deb` in a fresh Ubuntu 26.04 amd64 user profile.
Record method: a scripted native GUI action is not a human usability study.
Package smoke and native integration suites can automate the functional steps;
a release reviewer can repeat these manually with the installed Settings UI and
a local MCP client. Do not claim unperformed manual testing.

| Step | Expected observable result |
| --- | --- |
| 1. Install local package | APT resolves dependencies; Dia Fork and Dia MCP Settings appear; distribution Dia remains separate |
| 2. Launch Dia Fork with fresh profile | Normal GTK3 editor opens; live MCP is disabled and no endpoint exists |
| 3. Enable read-only in Settings; restart | Status/handshake show read-only, actual PID socket; no write capability |
| 4. Open a mixed-domain diagram | Native objects and any required trusted custom shapes load |
| 5. Inspect via MCP | Current context names the actual document/generation/layer |
| 6. Select objects manually | Selection highlights remain in Dia |
| 7. Explain selection | Selected IDs/types/properties/attachments correspond to those objects; truncation explicit |
| 8. Enable read/write and trusted root; restart | Status matches new mode/root; unchanged running processes are never relabeled |
| 9. Ask to align selection | Reviewable plan/static validation precedes the requested transaction |
| 10. Undo in Dia | Native Undo restores the previous geometry; no extra planning undo steps |
| 11. Create several objects | Native factories produce actual IDs and bounds |
| 12. Connect inspected ports | Native attachments visible in neighborhood/context; no guessed endpoints |
| 13. Save As inside root | Native .dia exists; filename/saved marker agree; overwrite explicit |
| 14. Export SVG and PNG | Files contain rendered output; document remains editable |
| 15. Restart Dia | Previous session IDs/receipts no longer resolve; new PID endpoint observed |
| 16. Reopen native file | Objects/connections survive with installed native plugins |
| 17. Reconnect MCP | Exact new endpoint handshakes; no automatic guessing between GUIs |
| 18. Inspect resulting document | New IDs, expected native types/topology, GUI responsive |

## Friction found and addressed

- Installed GUI initially could not import the live package without development
  PYTHONPATH. Package launchers expose only the integration package to embedded
  Python, leaving the MCP SDK in the external venv.
- The upstream desktop command `dia` could launch distribution Dia. The package
  uses separate absolute launchers and desktop IDs.
- Environment variables were the only first-run control. User settings/CLI and a
  separate GTK3 Settings window provide explicit modes without changing core Dia
  preferences. Restart is still required and clearly disclosed.
- The PID-specific endpoint changes on restart. Status lists observed endpoints;
  users must update/reconnect their client. Automatic GUI selection is deliberately
  absent because several diagrams/processes can exist.
- Compound properties, layer reassignment and formal domain validation remain
  unsupported and are reported rather than approximated.

The clean-user functional automation and GTK settings callbacks passed; see the
[M10 execution report](m10-validation.md). This checklist is retained for manual
review and is not a claim that a human performed every step.
