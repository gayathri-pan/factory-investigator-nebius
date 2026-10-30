-- Read-only: select one model-flagged held-out test window per machine.
-- Highest probability is deterministic demo selection, not an unbiased evaluation sample.
SELECT
  machine_id,
  FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', start_time, 'UTC') AS start_time,
  FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', end_time, 'UTC') AS cutoff_time,
  fault_probability, threshold, predicted_fault,
  `partition`, model_version, window_minutes, window_step_minutes,
  run_id AS source_run_id
FROM `project-e64210d0-f317-4050-833.factory_ai_investigator.xgboost_v3_window_predictions`
WHERE predicted_fault = 1
  AND `partition` = 'test'
  AND model_version = 'xgboost_30m_v3_dataset'
  AND machine_id IN ('M-101', 'M-102', 'M-103', 'M-104', 'M-105')
  AND window_minutes = 30
  AND window_step_minutes = 5
  AND TIMESTAMP_DIFF(end_time, start_time, SECOND) = 1740
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY machine_id ORDER BY fault_probability DESC, start_time, run_id
) = 1
ORDER BY machine_id;
