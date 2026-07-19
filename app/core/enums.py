from enum import StrEnum


class DataMode(StrEnum):
    MOCK = "mock"
    DEMO = "demo"
    REAL = "real"


class DataOrigin(StrEnum):
    MOCK = "mock"
    DEMO = "demo"
    REAL = "real"
    USER = "user"


class AgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AuditStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    REJECTED = "rejected"


class ImplementationStatus(StrEnum):
    SCAFFOLD = "scaffold"
    PRODUCTION = "production"


class KnowledgeType(StrEnum):
    PRODUCT_KNOWLEDGE = "product_knowledge"
    REVIEW_INSIGHT = "review_insight"


class RetrievalScope(StrEnum):
    EXACT_PRODUCT = "exact_product"
    PEER_GROUP = "peer_group"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class RunStageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class FileType(StrEnum):
    IMAGE = "image"
    MANUAL = "manual"
    DOCUMENT = "document"
    PARAMETER_FILE = "parameter_file"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    RESOURCE_NOT_FOUND = "resource_not_found"
    INVALID_RUN_STATE = "invalid_run_state"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    LLM_NOT_CONFIGURED = "llm_not_configured"
    KNOWLEDGE_UNAVAILABLE = "knowledge_unavailable"
    DATABASE_UNAVAILABLE = "database_unavailable"
    WORKFLOW_FAILED = "workflow_failed"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"
    DEMO_DATA_NOT_ALLOWED = "demo_data_not_allowed"
    DATA_PREPARATION_REQUIRED = "data_preparation_required"


class CustomerServicePersonality(StrEnum):
    SIMPLE = "simple"
    PROFESSIONAL = "professional"
    COMPANION = "companion"
    INNOVATIVE = "innovative"


class CustomerServiceIntent(StrEnum):
    EXPLAIN = "explain"
    LOCALIZED_EDIT = "localized_edit"
    MODIFY_STRATEGY = "modify_strategy"
    MODIFY_POSITIONING = "modify_positioning"
    MODIFY_MARKETING_COPY = "modify_marketing_copy"
    MODIFY_PROMOTION_STRATEGY = "modify_promotion_strategy"
    CLARIFICATION_REQUIRED = "clarification_required"
    REJECT = "reject"


class CustomerServiceAction(StrEnum):
    EXPLAIN = "explain"
    LOCALIZED_EDIT = "localized_edit"
    TARGETED_REGENERATION = "targeted_regeneration"
    POSITIONING_EDIT = "positioning_edit"
    MARKETING_COPY_EDIT = "marketing_copy_edit"
    PROMOTION_STRATEGY_EDIT = "promotion_strategy_edit"
    CLARIFICATION_REQUIRED = "clarification_required"
    REJECT = "reject"
