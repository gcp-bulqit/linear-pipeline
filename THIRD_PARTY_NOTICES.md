# Third-party notices

This repository includes material from the following third-party project. Its license is
reproduced in full as that license requires.

## mattpocock-skills: the /wizard library

- **Used in:** `scripts/onboard-repo.sh`, the section headed "Wizard library" (from the comment line
  "A wizard walks a human through a manual procedure, step by step." to the `STAGES` marker),
  reproduced without modification. The stages after that marker are original to this project.
- **Source:** the `/wizard` skill (`skills/engineering/wizard/template.sh`) in mattpocock-skills,
  version 1.2.3, https://github.com/mattpocock/skills
- **License:** MIT

```
MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Services the pipeline calls (no code included)

These are called over their public APIs at run time. No code from them is bundled here.

- **Linear** — GraphQL API (`https://api.linear.app/graphql`) and the Linear MCP server
  (`https://mcp.linear.app/mcp`).
- **GitHub CLI (`gh`)** — used to open draft pull requests.
- **TypeSafe** — used only by the optional add-on in `addons/jev-triage/`. See that directory's
  README before using it: it sends ticket text to that third-party service.
