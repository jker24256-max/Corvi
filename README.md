# Corvi

Corvi is a local-first terminal coding companion powered by Ollama. It can
inspect projects, explain code, run approved commands, edit files with review,
switch models, and optionally consult multiple local models with `/council`.

## Requirements

- macOS or Linux
- Python 3.9+
- Ollama installed and running
- At least one local Ollama model

## Run

From any project directory:

```bash
python3 /path/to/kit-project/kit.py
```

Or create a shell command named `corvi` that points to `kit.py`.

Corvi uses the directory where it is started as the active workspace. Use
`/cd /path/to/project` to switch workspaces.

## Useful commands

- `/help` — show all commands
- `/model` — list or change models
- `/pwd` — show the active workspace
- `/ls` — list files
- `/run COMMAND` — run a command after approval
- `/council PROMPT` — explicitly ask multiple models to collaborate
- `/yolo` — toggle automatic approval
- `/exit` — quit

Normal prompts use one model for faster responses. Council mode is opt-in.

## Ollama models

```bash
ollama serve
ollama list
ollama pull llama3.2:3b
```

Model files can be stored on an external drive by configuring Ollama's
`OLLAMA_MODELS` location before starting the service.

## Safety

Corvi asks before edits and shell commands by default. Local state, caches,
and desktop build artifacts are intentionally excluded from this repository.
