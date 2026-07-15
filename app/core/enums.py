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
