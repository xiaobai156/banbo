from enum import Enum


class FailureCode(str, Enum):
    NETWORK_ERROR = "network_error"
    SSL_ERROR = "ssl_error"
    HTTP_ERROR = "http_error"
    TARGET_PERIOD_MISSING = "target_period_missing"
    ANCHOR_MISSING = "anchor_missing"
    DIRECTION_MISMATCH = "direction_mismatch"
    DIRECTION_WINDOW_INVALID = "direction_window_invalid"
    FIELD_INVALID = "field_invalid"
    SAME_PERIOD_CONFLICT = "same_period_conflict"
    RECORD_ID_MISMATCH = "record_id_mismatch"
    DOCUMENT_BOUNDARY_MISMATCH = "document_boundary_mismatch"
    ADAPTIVE_MATCH_REJECTED = "adaptive_match_rejected"
    PARSER_SPEC_MISSING = "parser_spec_missing"
    INTERNAL_ERROR = "internal_error"
    MULTI_PERIOD_FAILED = "multi_period_failed"
