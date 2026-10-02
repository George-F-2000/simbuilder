"""
agent
================================================================================
A LOCAL, OFFLINE assistant for the Optimizer tab. A small open-weights model
(a GGUF file, run in-process by llama.cpp) reads the user's request and acts
through a FIXED tool list - the optimizer's own API, nothing else: no shell,
no file browser, no network. Every answer the model produces is constrained
by a grammar to one JSON object: either a tool call from the registry or a
final message, so an invalid or off-list call cannot be emitted.

Nothing leaves the machine, so this assistant may read the real log and the
study reports (the whole point of running it locally). The public code still
carries no vehicle data: the model file and its path are local settings.

Modules
  tools   the registry (name, description, JSON-schema parameters -> OptimizerApi)
  llm     the llama.cpp wrapper and the grammar built from the registry
  agent   the loop: prompt -> JSON -> dispatch -> ... -> final, with a transcript
  api     agent_* methods exposed on main.Api
================================================================================
"""
