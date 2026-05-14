# educlaw-builder

This template is the dedicated OAH workspace template for EduClaw profile generation.

Design goals:

- provide a deterministic machine-output assistant for profile building
- stay visible in OAH workspace template listings
- serve as the source template for `educlaw-builder-workspace`
- keep generation behavior separate from runtime teaching templates such as `educlaw-runtime`

Template contract:

- `builder` is the default entry agent
- output must follow caller-provided JSON / Markdown / plain-text constraints exactly
- this template is for profile generation and skill drafting, not end-user teaching dialogue