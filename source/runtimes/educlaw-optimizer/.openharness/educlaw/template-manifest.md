# educlaw-optimizer

This template is the dedicated OAH workspace template for iterative optimization of EduClaw agents and skills.

Design goals:

- provide a focused optimization workspace for existing agent / skill assets
- read current workspace evidence before proposing changes
- support direct-output workflows such as full file rewrites or structured diffs
- stay separate from generation (`educlaw-builder`) and runtime teaching (`micro-learning`)

Template contract:

- `assistant` is the default entry agent
- optimize existing definitions rather than inventing a new product flow by default
- preserve scenario intent while improving structure, clarity, and maintainability