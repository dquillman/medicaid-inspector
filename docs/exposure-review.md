# Storage exposure review and session precautions

The operational bucket formerly granted anonymous object reads. The privacy repair removed that grant and enforced public-access prevention. This establishes exposure potential, not that another party accessed records.

A metadata-only Cloud Logging query on October 28, 2026 covered the previous 30 days for Cloud Storage Data Access records in the operational bucket. It returned zero records. The project IAM audit configuration returned no configured auditConfigs. Inherited organization configuration, logs in other sinks, and access before that window were not established. Absence of logs does not demonstrate absence of access.

The release adds MFI_SESSIONS_VALID_AFTER, a deployment timestamp that rejects earlier tokens at startup, request validation, and persistence. Malformed/future session timestamps are rejected. Random bootstrap passwords are no longer written to application logs. No session tokens or credential hashes were inspected or retained for this review.

Production cutoff rollout and persisted-session cleanup are pending release verification. Password rotation is not claimed. Google sign-in credentials are held by Google; existing local account password hashes were potentially readable while the bucket was public. Existing users and case records are preserved.
