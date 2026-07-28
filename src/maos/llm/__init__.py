"""LLM_Provider_Adapter — the SOLE entry point for model calls (Req 8.1, TC-4).

Provider SDKs (anthropic, openai, boto3, google-genai) are imported ONLY within
this package. Agent logic under ``maos.graphs`` must never import them directly.
"""
