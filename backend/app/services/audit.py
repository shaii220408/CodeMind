import logging

logger = logging.getLogger("coderag.audit")


def audit_event(event: str, user_id: str | None, project_id: str | None = None, **details):
    logger.info(
        "audit_event",
        extra={"event": event, "user_id": user_id, "project_id": project_id, **details},
    )
