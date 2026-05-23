import json
import os
import logging
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger("ingestion")

# Try importing GCP libraries
try:
    from google.cloud import pubsub_v1

    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False


class TelemetryCollector:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.local_log_file = os.path.join(data_dir, "gameplay_events.jsonl")

        # GCP Config from env
        self.pubsub_topic = os.getenv("GCP_PUBSUB_TOPIC")
        self.gcp_project = os.getenv("GCP_PROJECT_ID")

        self.publisher = None
        if GCP_AVAILABLE and self.pubsub_topic and self.gcp_project:
            try:
                self.publisher = pubsub_v1.PublisherClient()
                self.topic_path = self.publisher.topic_path(
                    self.gcp_project, self.pubsub_topic
                )
                logger.info(
                    f"Initialized GCP Pub/Sub Publisher for topic: {self.topic_path}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to initialize GCP Pub/Sub: {e}. Falling back to local log."
                )
                self.publisher = None
        else:
            logger.info(
                "GCP Pub/Sub not configured. Running in Local Development Mode."
            )

    def record_event(self, event_data: Dict[str, Any]) -> None:
        """Records a gameplay event to the telemetry pipeline."""
        # Ensure timestamp is set
        if "timestamp" not in event_data:
            event_data["timestamp"] = datetime.utcnow().isoformat() + "Z"

        # 1. Write to local timeseries file (JSONL format)
        try:
            with open(self.local_log_file, "a") as f:
                f.write(json.dumps(event_data) + "\n")
        except Exception as e:
            logger.error(f"Failed to write event locally: {e}")

        # 2. Publish to GCP Pub/Sub if configured
        if self.publisher:
            try:
                # Convert event to bytes
                data_str = json.dumps(event_data)
                data_bytes = data_str.encode("utf-8")
                # Publish asynchronously
                self.publisher.publish(self.topic_path, data_bytes)
                # We can add a callback or block briefly, but let's run non-blocking
                logger.info(
                    f"Published event {event_data.get('action_taken')} to Pub/Sub."
                )
            except Exception as e:
                logger.error(f"Failed to publish to GCP Pub/Sub: {e}")

    def get_events(self, limit: int = 100) -> list:
        """Reads the local JSONL log and returns the latest events."""
        if not os.path.exists(self.local_log_file):
            return []

        events = []
        try:
            with open(self.local_log_file, "r") as f:
                lines = f.readlines()
                # Return the last N events
                for line in lines[-limit:]:
                    if line.strip():
                        events.append(json.loads(line.strip()))
        except Exception as e:
            logger.error(f"Failed to read local events: {e}")

        return events

    def clear_local_events(self) -> None:
        """Clears the local JSONL event log."""
        if os.path.exists(self.local_log_file):
            try:
                os.remove(self.local_log_file)
                logger.info("Cleared local events file.")
            except Exception as e:
                logger.error(f"Failed to clear events: {e}")
