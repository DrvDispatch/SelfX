"""Natural-language agent: a thin function-calling gateway that lets a brain (local
Ollama by default, or Gemini when a key is set) drive SelfX's own validated tools.
Files stay local — the model only ever sees ids/names/summaries. See RAG_AGENT_PLAN.md."""
