"""Honest PR-03 feature gate; registry is not proof of web entitlements."""

def capabilities() -> dict:
    return {
        "orchestrator_version": "pr03-offline",
        "logical_worker_limit": 5,
        "enabled_transports": ["mock"],
        "remote_generations_available": 0,
        "browser_sessions_verified": 0,
        "callback_delivery": "local-persisted-outbox-only",
        "chatgpt_ui_uploads": False,
        "chatgpt_apps_plugins": False,
        "gpt6_high_verified": False,
        "external_mutations": False,
        "automatic_resend_after_unknown": False,
    }